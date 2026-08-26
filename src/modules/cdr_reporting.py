"""NetCheck CDR report preparation and template-backed PPT rendering."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches


TEMPLATE_NAMES = {
    "nsa": "Template_CDR_NSA_analysis.pptx",
    "sa": "Template_CDR_SA_analysis.pptx",
}
CDR_REPORT_VERSION = "2026-08-26-v3"
REPORTING_KINDS = {"data", "voice", "speech"}
COMMENT_HINTS = ("having ", "observed", "shows ", "similar performance", "worse ", "improvement", "degradation", "gap ")


@dataclass(frozen=True)
class ReportSelection:
    data_id: int
    voice_id: int
    speech_id: int
    technology: str
    multivendor: bool
    vodafone_mapping_id: int | None = None
    three_mapping_id: int | None = None


def _normalise_operator(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"three", "3", "3 uk", "three uk"}:
        return "3"
    if text.lower() in {"vodafone", "vodafone uk", "vodafone-uk"}:
        return "Vodafone UK"
    return text


def _split_global_cells(value: object) -> list[str]:
    """Return ordered Global CI values from NetCheck's timeline/list formatting."""
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return []
    parts = re.split(r"\s*(?:->|;|,|\||\]\s*\[)\s*", text.strip("[] "))
    return [_canonical_cell_id(part) for part in parts if part.strip(" []'\"")]


def _canonical_cell_id(value: object) -> str:
    text = str(value or "").strip(" []'\"")
    if re.fullmatch(r"\d+\.0+", text):
        return text.split('.', 1)[0]
    return text


def vendor_from_cells(operator: object, cells: object, vendor_lookup: dict[str, str]) -> str:
    """Implement the business formula supplied for Vodafone and Three.

    Vodafone's Ericsson/null exceptions deliberately resolve to Mixed Vendor,
    exactly as specified by the reference formula.
    """
    normalized_operator = _normalise_operator(operator)
    if normalized_operator not in {"Vodafone UK", "3"}:
        return normalized_operator
    global_cells = _split_global_cells(cells)
    first = vendor_lookup.get(global_cells[0]) if global_cells else None
    last = vendor_lookup.get(global_cells[-1]) if global_cells else None
    if normalized_operator == "Vodafone UK":
        if first and first == last:
            return f"Vodafone_{first}"
        if (first == "Ericsson" and last != "Ericsson") or (last == "Ericsson" and first != "Ericsson"):
            return "Vodafone_Mixed Vendor"
        return "Vodafone_Other Vendor"
    if first and first == last:
        return f"3_{first}"
    return "3_Mixed Vendor"


def _first_existing(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lookup = {str(column).lower(): str(column) for column in df.columns}
    for candidate in candidates:
        actual = lookup.get(candidate.lower())
        if actual:
            return actual
    return None


def classify_sessions(df: pd.DataFrame, technology: str) -> pd.DataFrame:
    rat_column = _first_existing(df, ["RAT", "RAT_A", "Sample_RAT_A", "technology_primary"])
    if not rat_column:
        raise ValueError("The selected CDR does not contain RAT, RAT_A or Sample_RAT_A, required to separate NSA and SA sessions.")
    # NetCheck exports use both ENDC and EN-DC (sometimes EN DC) for NSA.
    # The business filter is the technology concept, not one file spelling.
    marker = r"EN[- ]?DC" if technology == "nsa" else r"NR"
    return df[df[rat_column].astype(str).str.contains(marker, case=False, na=False, regex=True)].copy()


def _integer_cell_component(value: object) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_three_vendor_lookup(mapping: pd.DataFrame) -> dict[str, str]:
    cell_column = _first_existing(mapping, ["Cid__ECI", "CId___ECI"])
    vendor_column = _first_existing(mapping, ["Vendor", "OP/ Vendor", "OP_Vendor"])
    if not cell_column or not vendor_column:
        raise ValueError("The selected 3UK mapping must contain Cid__ECI and a Vendor column.")
    lookup: dict[str, str] = {}
    for cell, vendor in mapping[[cell_column, vendor_column]].dropna().itertuples(index=False):
        cell_text, vendor_text = _canonical_cell_id(cell), str(vendor).strip()
        if cell_text and vendor_text:
            lookup[cell_text] = vendor_text
    return lookup


def build_vodafone_vendor_lookup(mapping: pd.DataFrame) -> dict[str, str]:
    source_sheet = _first_existing(mapping, ["source_sheet"])
    five_g_mapping = mapping
    if source_sheet:
        five_g_mapping = mapping[mapping[source_sheet].astype(str).str.strip().str.casefold() == "5g"].copy()
    gnodeb_column = _first_existing(five_g_mapping, ["gNodeB ID", "gNodeB_ID"])
    local_cell_column = _first_existing(five_g_mapping, ["Local Cell ID", "Local_Cell_ID"])
    vendor_column = _first_existing(five_g_mapping, ["OP/ Vendor", "OP_Vendor", "Vendor"])
    if five_g_mapping.empty or not gnodeb_column or not local_cell_column or not vendor_column:
        raise ValueError("The selected VFUK mapping must contain the 5G sheet with gNodeB ID, Local Cell ID and OP/ Vendor columns.")
    lookup: dict[str, str] = {}
    for gnodeb, local_cell, vendor in five_g_mapping[[gnodeb_column, local_cell_column, vendor_column]].itertuples(index=False):
        gnodeb_id = _integer_cell_component(gnodeb)
        local_cell_id = _integer_cell_component(local_cell)
        vendor_text = str(vendor).strip()
        if gnodeb_id is None or local_cell_id is None or not vendor_text or vendor_text.lower() == "nan":
            continue
        lookup[str(gnodeb_id * 4096 + local_cell_id)] = vendor_text
    return lookup


def enrich_multivendor(df: pd.DataFrame, vodafone_mapping: pd.DataFrame, three_mapping: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    operator_column = _first_existing(result, ["operator", "Operator"])
    cell_column = _first_existing(result, ["Cell_ID_A"])
    if not operator_column or not cell_column:
        raise ValueError("The selected CDR must contain Operator and Cell_ID_A for multivendor reporting.")
    vodafone_lookup = build_vodafone_vendor_lookup(vodafone_mapping)
    three_lookup = build_three_vendor_lookup(three_mapping)
    result["report_vendor"] = [
        vendor_from_cells(
            operator,
            cells,
            vodafone_lookup if _normalise_operator(operator) == "Vodafone UK" else three_lookup,
        )
        for operator, cells in result[[operator_column, cell_column]].itertuples(index=False)
    ]
    return result


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _bar_chart(title: str, summary: pd.DataFrame) -> BytesIO:
    image = Image.new("RGB", (1100, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 20), title, fill="#102131", font=_font(28, True))
    if summary.empty:
        draw.text((30, 260), "No valid samples for this KPI and technology filter", fill="#61727D", font=_font(22))
    else:
        maximum = max(float(summary["value"].max()), 1.0)
        colors = ["#0B7A75", "#245A96", "#DD653E", "#6D46A8", "#228A5D", "#C78B1D"]
        for index, row in summary.reset_index(drop=True).iterrows():
            y = 95 + index * 62
            width = int(650 * float(row["value"]) / maximum)
            draw.text((30, y + 10), str(row["group"])[:28], fill="#102131", font=_font(18))
            draw.rectangle((330, y, 330 + width, y + 36), fill=colors[index % len(colors)])
            draw.text((1000, y + 8), f"{float(row['value']):.1f}", fill="#102131", font=_font(18, True))
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def _summary_for_slide(frames: dict[str, pd.DataFrame], title: str, multivendor: bool) -> pd.DataFrame:
    normalized_title = title.lower()
    source = frames["data"] if any(token in normalized_title for token in ("fdfs", "fdtt", "interactivity", "browsing", "data failure")) else frames["speech"] if "polqa" in normalized_title else frames["voice"]
    metric_candidates = ["throughput_mbps", "quality_score", "success", "failure", "setup_time_seconds", "duration_seconds"]
    aggregation = "mean"
    if "failure" in normalized_title:
        metric_candidates, aggregation = ["failure", "dropped"], "mean"
    elif "completed" in normalized_title or "success ratio" in normalized_title:
        metric_candidates, aggregation = ["success"], "mean"
    elif "polqa <1.6" in normalized_title:
        metric_candidates, aggregation = ["POLQA_LQ_Avg", "LQ", "quality_score"], "low_polqa_rate"
    elif "polqa avg" in normalized_title:
        metric_candidates = ["POLQA_LQ_Avg", "LQ", "quality_score"]
    elif "cst" in normalized_title:
        metric_candidates = ["Call_Setup_Time", "setup_time_seconds"]
    elif "interactivity" in normalized_title:
        metric_candidates = ["Interactivity_Duration", "latency_ms"]
    elif "browsing" in normalized_title:
        metric_candidates = ["http_Browser_1MB_Reached_Duration", "setup_time_seconds"]
    elif "throughput" in normalized_title or "fdtt" in normalized_title or "fdfs" in normalized_title:
        metric_candidates = ["Mean_Data_Rate", "throughput_mbps"]
    metric = next((item for item in metric_candidates if item in source.columns), None)
    group_column = "report_vendor" if multivendor and "report_vendor" in source.columns else _first_existing(source, ["operator", "Operator"])
    if not metric or not group_column:
        return pd.DataFrame(columns=["group", "value"])
    values = source[[group_column, metric]].copy()
    values[metric] = pd.to_numeric(values[metric], errors="coerce")
    values = values.dropna(subset=[group_column, metric])
    if values.empty:
        return pd.DataFrame(columns=["group", "value"])
    if aggregation == "low_polqa_rate":
        values[metric] = values[metric].lt(1.6).astype(float) * 100
    elif metric in {"success", "failure", "dropped"}:
        values[metric] = values[metric].astype(float) * 100
    return values.groupby(group_column, dropna=False)[metric].mean().reset_index(name="value").rename(columns={group_column: "group"}).head(8)


def _clear_commentary(slide) -> None:
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        text = shape.text.strip().lower()
        if len(text) > 45 and any(hint in text for hint in COMMENT_HINTS):
            shape.text_frame.clear()


def _chart_frames(slide) -> list[tuple[int, int, int, int]]:
    """Remove example chart images/groups and return their occupied areas.

    Logos and small decorative images remain untouched. The new report chart is
    placed in the exact bounding area of the removed template chart(s).
    """
    removable_types = {MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.GROUP}
    frames: list[tuple[int, int, int, int]] = []
    for shape in list(slide.shapes):
        if shape.shape_type not in removable_types:
            continue
        area = shape.width * shape.height
        if shape.top < Inches(0.9) or area < Inches(1.5) * Inches(1.5):
            continue
        frames.append((shape.left, shape.top, shape.width, shape.height))
        shape._element.getparent().remove(shape._element)
    return frames


def _combined_frame(frames: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not frames:
        return None
    left = min(frame[0] for frame in frames)
    top = min(frame[1] for frame in frames)
    right = max(frame[0] + frame[2] for frame in frames)
    bottom = max(frame[1] + frame[3] for frame in frames)
    return left, top, right - left, bottom - top


def render_cdr_report(destination: Path, template: Path, frames: dict[str, pd.DataFrame], technology: str, multivendor: bool) -> Path:
    if not template.exists():
        raise FileNotFoundError(f"Reporting template not found: {template.name}")
    shutil.copyfile(template, destination)
    presentation = Presentation(destination)
    excluded = {1, 2, 3, 4, 5, 6} if technology == "nsa" else set(range(1, 11))
    for number, slide in enumerate(presentation.slides, start=1):
        _clear_commentary(slide)
        if number in excluded:
            continue
        title = next((shape.text.strip() for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip()), "CDR KPI")
        if title.lower() in {"conclusions", "agenda", "actions tracker"} or "analysis" in title.lower() and "cdr" in title.lower():
            continue
        summary = _summary_for_slide(frames, title, multivendor)
        chart = _bar_chart(title, summary)
        chart_frame = _combined_frame(_chart_frames(slide))
        if not chart_frame:
            chart_frame = (Inches(0.55), Inches(1.65), Inches(6.15), Inches(3.75))
        slide.shapes.add_picture(chart, *chart_frame)
    presentation.save(destination)
    return destination
