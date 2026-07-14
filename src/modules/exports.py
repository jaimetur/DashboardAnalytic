from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

SLIDE_WIDTH = 960
SLIDE_HEIGHT = 540
CHART_BG = "#F5FBFA"
PANEL_BG = "#FFFFFF"
TEXT_DARK = "#12383A"
TEXT_MUTED = "#5F7D7E"
ACCENT = "#12B5A5"
ACCENT_ALT = "#1F6FEB"
ACCENT_WARN = "#F59E0B"
GRID = "#D5E6E5"
SERIES_COLORS = [
    "#12B5A5",
    "#1F6FEB",
    "#F59E0B",
    "#E11D48",
    "#7C3AED",
    "#0F766E",
    "#C2410C",
    "#334155",
]


def export_word_report(destination: Path, analysis: dict[str, Any]) -> Path:
    document = Document()
    document.add_heading("Dashboard Analytic Report", level=0)
    document.add_paragraph(f"Metric analysed: {analysis['selected_metric']}")
    document.add_paragraph(f"Filtered rows: {analysis['kpis']['rows']}")

    document.add_heading("Key KPIs", level=1)
    for key, value in analysis["kpis"].items():
        document.add_paragraph(f"{key}: {value}")

    document.add_heading("Scorecard", level=1)
    for row in analysis["scorecard"]:
        document.add_paragraph(f"{row['label']}: {row['value']}")

    document.save(destination)
    return destination


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _format_label(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "n/a"
    return normalized.replace("_", " ").title()


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _filters_summary(filters: dict[str, Any]) -> str:
    fragments: list[str] = []
    for key in ["market", "period"]:
        values = filters.get(key) or []
        if values:
            fragments.append(f"{_format_label(key)}: {', '.join(str(item) for item in values)}")
    for key, values in (filters.get("extra_filters") or {}).items():
        if not values or values == ["__none__"]:
            continue
        if not isinstance(values, list):
            values = [values]
        fragments.append(f"{_format_label(key)}: {', '.join(str(item) for item in values)}")
    if filters.get("date_from"):
        fragments.append(f"Date From: {filters['date_from']}")
    if filters.get("date_to"):
        fragments.append(f"Date To: {filters['date_to']}")
    if not fragments:
        return "No filters selected"
    return " | ".join(fragments)


def _add_textbox(slide, left: float, top: float, width: float, height: float, text: str, size: int = 14, bold: bool = False,
                 color: str = TEXT_DARK, align: PP_ALIGN = PP_ALIGN.LEFT) -> None:
    textbox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = textbox.text_frame
    frame.clear()
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.alignment = align
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))


def _add_context_banner(slide, dataset_name: str, filters_text: str, metric_name: str | None = None) -> None:
    dataset_text = f"Dataset: {dataset_name}"
    if metric_name:
        dataset_text += f" | Metric: {metric_name}"
    _add_textbox(slide, 0.55, 0.25, 12.0, 0.28, dataset_text, size=12, bold=True, color=ACCENT_ALT)
    _add_textbox(slide, 0.55, 0.52, 12.0, 0.42, filters_text, size=10, color=TEXT_MUTED)


def _draw_wrapped_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont,
                       fill: str = TEXT_DARK, line_spacing: int = 8) -> None:
    x0, y0, x1, y1 = box
    max_width = max(50, x1 - x0)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    y = y0
    for line in lines:
        draw.text((x0, y), line, font=font, fill=fill)
        y += font.size + line_spacing
        if y > y1:
            break


def _empty_chart_image(message: str) -> BytesIO:
    image = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), CHART_BG)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(28, bold=True)
    body_font = _load_font(20)
    draw.rounded_rectangle((40, 40, SLIDE_WIDTH - 40, SLIDE_HEIGHT - 40), radius=24, fill=PANEL_BG, outline=GRID, width=2)
    draw.text((80, 120), "No chart data", font=title_font, fill=TEXT_DARK)
    _draw_wrapped_text(draw, (80, 180, SLIDE_WIDTH - 80, SLIDE_HEIGHT - 80), message, body_font, fill=TEXT_MUTED)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_bar_chart(chart: dict[str, Any]) -> BytesIO:
    labels = [str(value) for value in chart.get("labels", [])]
    values = [float(value) for value in chart.get("series", [])]
    if not labels or not values:
        return _empty_chart_image("The selected comparison does not contain grouped values for this metric.")

    image = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), CHART_BG)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(22, bold=True)
    axis_font = _load_font(16)
    value_font = _load_font(15, bold=True)
    draw.rounded_rectangle((24, 24, SLIDE_WIDTH - 24, SLIDE_HEIGHT - 24), radius=20, fill=PANEL_BG, outline=GRID, width=2)
    draw.text((48, 36), "Group Benchmark", font=title_font, fill=TEXT_DARK)

    left, top, right, bottom = 90, 110, SLIDE_WIDTH - 60, SLIDE_HEIGHT - 90
    draw.line((left, top, left, bottom), fill=TEXT_MUTED, width=2)
    draw.line((left, bottom, right, bottom), fill=TEXT_MUTED, width=2)

    max_value = max(values) if values else 1.0
    if max_value <= 0:
        max_value = 1.0
    count = max(1, len(values))
    gap = 16
    usable_width = right - left - gap * (count + 1)
    bar_width = max(28, usable_width // count)
    chart_height = bottom - top - 24

    for index, (label, value) in enumerate(zip(labels[:8], values[:8], strict=False)):
        x0 = left + gap + index * (bar_width + gap)
        x1 = x0 + bar_width
        bar_height = int((value / max_value) * chart_height) if max_value else 0
        y0 = bottom - bar_height
        draw.rounded_rectangle((x0, y0, x1, bottom), radius=12, fill=ACCENT)
        value_text = _format_value(value)
        text_width = draw.textlength(value_text, font=value_font)
        if bar_height > 34:
            draw.text((x0 + (bar_width - text_width) / 2, y0 + 8), value_text, font=value_font, fill="#FFFFFF")
        else:
            draw.text((x0 + (bar_width - text_width) / 2, max(top + 8, y0 - 22)), value_text, font=value_font, fill=TEXT_DARK)
        short_label = label if len(label) <= 14 else f"{label[:12]}.."
        text_width = draw.textlength(short_label, font=axis_font)
        draw.text((x0 + (bar_width - text_width) / 2, bottom + 10), short_label, font=axis_font, fill=TEXT_MUTED)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_line_chart(chart: dict[str, Any]) -> BytesIO:
    if chart.get("series_collection"):
        series_collection = [
            {
                "name": str(item.get("name") or "Series"),
                "labels": [float(value) for value in item.get("labels", [])],
                "series": [float(value) for value in item.get("series", [])],
            }
            for item in chart.get("series_collection", [])
            if item.get("labels") and item.get("series")
        ]
    else:
        labels = [float(value) for value in chart.get("labels", [])]
        series = [float(value) for value in chart.get("series", [])]
        series_collection = [{"name": "CDF", "labels": labels, "series": series}] if labels and series else []

    if not series_collection:
        return _empty_chart_image("The selected CDF comparison does not contain numeric values for this metric.")

    image = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), CHART_BG)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(22, bold=True)
    body_font = _load_font(15)
    draw.rounded_rectangle((24, 24, SLIDE_WIDTH - 24, SLIDE_HEIGHT - 24), radius=20, fill=PANEL_BG, outline=GRID, width=2)
    draw.text((48, 36), "CDF Curve", font=title_font, fill=TEXT_DARK)

    left, top, right, bottom = 90, 110, SLIDE_WIDTH - 60, SLIDE_HEIGHT - 120
    draw.line((left, top, left, bottom), fill=TEXT_MUTED, width=2)
    draw.line((left, bottom, right, bottom), fill=TEXT_MUTED, width=2)

    all_x = [value for series_item in series_collection for value in series_item["labels"]]
    all_y = [value for series_item in series_collection for value in series_item["series"]]
    min_x = min(all_x) if all_x else 0.0
    max_x = max(all_x) if all_x else 1.0
    min_y = min(all_y) if all_y else 0.0
    max_y = max(all_y) if all_y else 1.0
    if max_x == min_x:
        max_x = min_x + 1.0
    if max_y == min_y:
        max_y = min_y + 1.0

    for index, series_item in enumerate(series_collection[:8]):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        points: list[tuple[float, float]] = []
        for x_value, y_value in zip(series_item["labels"], series_item["series"], strict=False):
            px = left + ((x_value - min_x) / (max_x - min_x)) * (right - left)
            py = bottom - ((y_value - min_y) / (max_y - min_y)) * (bottom - top)
            points.append((px, py))
        if len(points) >= 2:
            draw.line(points, fill=color, width=4)
        for point in points[::max(1, len(points) // 12 or 1)]:
            draw.ellipse((point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3), fill=color)

    legend_y = SLIDE_HEIGHT - 90
    legend_x = 60
    for index, series_item in enumerate(series_collection[:8]):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        draw.rounded_rectangle((legend_x, legend_y, legend_x + 18, legend_y + 18), radius=5, fill=color)
        draw.text((legend_x + 26, legend_y - 2), series_item["name"], font=body_font, fill=TEXT_MUTED)
        legend_x += 160
        if legend_x > SLIDE_WIDTH - 180:
            legend_x = 60
            legend_y += 24

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _add_kpi_grid(slide, items: list[tuple[str, Any]], left: float, top: float, width: float, card_height: float = 0.72,
                  columns: int = 3, accent_color: str = ACCENT) -> None:
    if not items:
        return
    gap_x = 0.14
    gap_y = 0.12
    column_width = (width - gap_x * (columns - 1)) / columns
    for index, (label, value) in enumerate(items):
        row = index // columns
        column = index % columns
        x = left + column * (column_width + gap_x)
        y = top + row * (card_height + gap_y)
        shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(column_width), Inches(card_height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string("F7FBFB")
        shape.line.color.rgb = RGBColor.from_string(accent_color.lstrip("#"))
        shape.line.width = Pt(1)
        _add_textbox(slide, x + 0.12, y + 0.08, column_width - 0.24, 0.2, _format_label(label), size=9, color=TEXT_MUTED)
        _add_textbox(slide, x + 0.12, y + 0.3, column_width - 0.24, 0.28, _format_value(value), size=17, bold=True, color=TEXT_DARK)


def _add_grouped_scorecard_table(slide, groups: list[dict[str, Any]], left: float, top: float, width: float, height: float) -> None:
    if not groups:
        _add_textbox(slide, left, top, width, 0.35, "No percentile groups available for this metric.", size=12, color=TEXT_MUTED)
        return
    rows = len(groups) + 1
    cols = 6
    table = slide.shapes.add_table(rows, cols, Inches(left), Inches(top), Inches(width), Inches(height)).table
    headers = ["Group", "P10", "P25", "P50", "P75", "P90"]
    for index, header in enumerate(headers):
        cell = table.cell(0, index)
        cell.text = header
        for paragraph in cell.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.bold = True
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor.from_string(TEXT_DARK.lstrip("#"))
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor.from_string("EAF5F4")

    for row_index, group in enumerate(groups, start=1):
        values_by_label = {str(item.get("label")): item.get("value") for item in group.get("items") or []}
        row_values = [
            str(group.get("group") or "Overall"),
            _format_value(values_by_label.get("P10", "-")),
            _format_value(values_by_label.get("P25", "-")),
            _format_value(values_by_label.get("P50", "-")),
            _format_value(values_by_label.get("P75", "-")),
            _format_value(values_by_label.get("P90", "-")),
        ]
        for col_index, value in enumerate(row_values):
            cell = table.cell(row_index, col_index)
            cell.text = value
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)
                    run.font.color.rgb = RGBColor.from_string(TEXT_DARK.lstrip("#"))
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string("FFFFFF" if row_index % 2 else "F7FBFB")


def _build_powerpoint_payload(report: dict[str, Any]) -> dict[str, Any]:
    analyses = report.get("analyses") or []
    primary = analyses[0]["result"] if analyses else None
    return {
        "dataset_name": report.get("dataset_name") or "Dataset",
        "dataset_type": report.get("dataset_type") or "Other",
        "filters_text": report.get("filters_text") or "No filters selected",
        "selected_metrics": report.get("selected_metrics") or [],
        "global_kpis": (primary or {}).get("global_kpis") or {},
        "analyses": analyses,
    }


def export_powerpoint_report(destination: Path, report: dict[str, Any]) -> Path:
    payload = _build_powerpoint_payload(report)
    presentation = Presentation()

    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = "Dashboard Analytic"
    subtitle = title_slide.placeholders[1]
    subtitle.text = f"{payload['dataset_name']}\n{payload['dataset_type']}\n{payload['filters_text']}"

    global_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    global_slide.shapes.title.text = "Executive Dashboard"
    _add_context_banner(global_slide, payload["dataset_name"], payload["filters_text"])
    global_items = [
        (key, value) for key, value in payload["global_kpis"].items()
        if key not in {"date_from", "date_to"}
    ]
    _add_kpi_grid(global_slide, global_items[:15], left=0.55, top=1.2, width=12.0, columns=3, accent_color=ACCENT_ALT)

    for analysis_item in payload["analyses"]:
        result = analysis_item["result"]
        metric_name = result.get("selected_metric") or analysis_item.get("metric") or "Metric"

        charts_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        charts_slide.shapes.title.text = f"Visual Analytics - {metric_name}"
        _add_context_banner(charts_slide, payload["dataset_name"], payload["filters_text"], metric_name=metric_name)
        cdf_image = _draw_line_chart(result.get("cdf_chart") or {})
        comparison_image = _draw_bar_chart(result.get("comparison_chart") or {})
        charts_slide.shapes.add_picture(cdf_image, Inches(0.55), Inches(1.2), width=Inches(5.75), height=Inches(2.55))
        charts_slide.shapes.add_picture(comparison_image, Inches(6.45), Inches(1.2), width=Inches(5.55), height=Inches(2.55))
        metric_items = [
            (key, value)
            for key, value in (result.get("metric_kpis") or {}).items()
            if key not in {"metric"}
        ]
        _add_kpi_grid(charts_slide, metric_items, left=0.55, top=3.95, width=12.0, columns=4, accent_color=ACCENT)
        _add_textbox(charts_slide, 0.55, 5.45, 3.2, 0.24, "Grouped Percentiles", size=11, bold=True, color=ACCENT_WARN)
        _add_grouped_scorecard_table(charts_slide, (result.get("scorecard_groups") or [])[:8], left=0.55, top=5.7, width=12.0, height=1.2)

    presentation.save(destination)
    return destination
