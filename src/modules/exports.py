from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from pptx import Presentation
from pptx.util import Inches


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


def export_powerpoint_report(destination: Path, analysis: dict[str, Any]) -> Path:
    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = "Dashboard Analytic"
    title_slide.placeholders[1].text = f"Automatic KPI report for {analysis['selected_metric']}"

    kpi_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    kpi_slide.shapes.title.text = "KPI Summary"
    textbox = kpi_slide.shapes.add_textbox(Inches(0.6), Inches(1.4), Inches(8.5), Inches(4.5))
    frame = textbox.text_frame
    for key, value in analysis["kpis"].items():
        paragraph = frame.add_paragraph()
        paragraph.text = f"{key}: {value}"

    score_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    score_slide.shapes.title.text = "Scorecard"
    score_box = score_slide.shapes.add_textbox(Inches(0.6), Inches(1.4), Inches(8.5), Inches(4.5))
    score_frame = score_box.text_frame
    for item in analysis["scorecard"]:
        paragraph = score_frame.add_paragraph()
        paragraph.text = f"{item['label']}: {item['value']}"

    presentation.save(destination)
    return destination
