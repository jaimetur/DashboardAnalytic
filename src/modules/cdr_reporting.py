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
CDR_REPORT_VERSION = "2026-08-26-v5"
REPORTING_KINDS = {"data", "voice", "speech"}
COMMENT_HINTS = ("having ", "observed", "shows ", "similar performance", "worse ", "improvement", "degradation", "gap ")

# The PPT templates contain rasterised Tableau charts.  These rules are the
# source-of-truth replacement contract captured from every automated KPI slide:
# source CDR, visual grammar, KPI, and the template's test/session filters.
REPORT_CHART_SPECS = {
    "nsa": {
        8: {"kind": "status_100", "source": "voice", "sessions": ("volte", "multirab", "whatsapp")},
        9: {"kind": "failure_count", "source": "voice", "sessions": ("volte", "multirab", "whatsapp")},
        10: {"kind": "status_100", "source": "data", "tests": ("http", "youtube", "video", "brows")},
        11: {"kind": "status_100", "source": "data", "tests": ("fdfs",)},
        12: {"kind": "cdf_mean", "source": "voice", "metric": ("POLQA_LQ_Avg", "quality_score"), "sessions": ("volte", "multirab")},
        13: {"kind": "cdf_mean", "source": "speech", "metric": ("LQ", "quality_score"), "sessions": ("whatsapp",)},
        14: {"kind": "dual_quality_100", "source": "speech", "metric": ("LQ", "quality_score"), "sessions": ("whatsapp",), "threshold": 1.6,
             "secondary": {"source": "voice", "metric": ("POLQA_LQ_Avg", "quality_score"), "sessions": ("volte",)}},
        15: {"kind": "cdf_mean", "source": "voice", "metric": ("Call_Setup_Time", "setup_time_seconds"), "sessions": ("volte", "multirab")},
        16: {"kind": "cdf_bucket", "source": "data", "metric": ("FDTT_Sustainable_MDR", "Mean_Data_Rate", "throughput_mbps"), "tests": ("fdtt",), "directions": ("dl",)},
        17: {"kind": "cdf_bucket", "source": "data", "metric": ("FDTT_Sustainable_MDR", "Mean_Data_Rate", "throughput_mbps"), "tests": ("fdtt",), "directions": ("ul",)},
        18: {"kind": "cdf_pair", "source": "data", "metric": ("Mean_Data_Rate", "throughput_mbps"), "secondary_metric": ("Data_Test_Duration", "Transfer_Duration", "duration_seconds"), "tests": ("fdfs",), "directions": ("dl",)},
        19: {"kind": "cdf_pair", "source": "data", "metric": ("Mean_Data_Rate", "throughput_mbps"), "secondary_metric": ("Data_Test_Duration", "Transfer_Duration", "duration_seconds"), "tests": ("fdfs",), "directions": ("ul",)},
        20: {"kind": "cdf_pair", "source": "data", "metric": ("Interactivity_RTT_Median", "Interactivity_RTT_AVG", "latency_ms"), "secondary_metric": ("Interactivity_Packet_Error_Ratio", "Packet_Error_Ratio"), "tests": ("interactivity",)},
        21: {"kind": "cdf_mean", "source": "data", "metric": ("http_Browser_1MB_Reached_Duration", "http_Browser_Access_Duration", "setup_time_seconds"), "tests": ("brows", "http")},
    },
    "sa": {
        12: {"kind": "failure_count", "source": "voice", "sessions": ("call", "multirab", "whatsapp")},
        13: {"kind": "failure_count", "source": "voice", "operators": ("vodafone",), "sessions": ("call", "multirab", "whatsapp")},
        14: {"kind": "status_100", "source": "voice", "sessions": ("call", "multirab", "whatsapp")},
        15: {"kind": "quality_100", "source": "speech", "metric": ("LQ", "quality_score"), "threshold": 1.6},
        16: {"kind": "scatter", "source": "speech", "metric": ("LQ", "quality_score"), "x_metric": ("Playing_RSRP_NR_Avg", "NR_RSRP_Avg"), "operators": ("vodafone",), "sessions": ("whatsapp",)},
        17: {"kind": "quality_cdf", "source": "speech", "metric": ("LQ", "quality_score"), "sessions": ("whatsapp",), "operators": ("three", "3 uk", "3") , "threshold": 1.6},
        18: {"kind": "cdf_mean", "source": "voice", "metric": ("POLQA_LQ_Avg", "quality_score"), "sessions": ("call", "multirab", "whatsapp")},
        19: {"kind": "cdf_mean", "source": "voice", "metric": ("POLQA_LQ_Avg", "quality_score"), "sessions": ("call", "multirab", "whatsapp"), "city_scope": "london"},
        21: {"kind": "status_100", "source": "data", "tests": ("fdfs",)},
        22: {"kind": "cdf_mean", "source": "data", "metric": ("Mean_Data_Rate", "throughput_mbps"), "tests": ("fdfs",), "directions": ("dl",)},
        23: {"kind": "cdf_mean", "source": "data", "metric": ("Mean_Data_Rate", "throughput_mbps"), "tests": ("fdfs",), "directions": ("ul",)},
        24: {"kind": "cdf_mean", "source": "data", "metric": ("FDTT_Sustainable_MDR", "Mean_Data_Rate", "throughput_mbps"), "tests": ("fdtt",)},
        25: {"kind": "cdf_mean", "source": "data", "metric": ("Interactivity_RTT_Median", "Interactivity_RTT_AVG", "latency_ms"), "tests": ("interactivity",)},
        26: {"kind": "cdf_mean", "source": "data", "metric": ("http_Browser_1MB_Reached_Duration", "http_Browser_Access_Duration", "setup_time_seconds"), "tests": ("brows", "http")},
    },
}

OPERATOR_COLORS = {"3": "#F28E2B", "three": "#F28E2B", "ee": "#4E79A7", "vf": "#E15759", "vodafone": "#E15759", "o2": "#B07AA1"}


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
    four_g_mapping = mapping
    if source_sheet:
        four_g_mapping = mapping[mapping[source_sheet].astype(str).str.strip().str.casefold() == "4g"].copy()
    enodeb_column = _first_existing(four_g_mapping, ["eNodeB ID", "eNodeB_ID"])
    local_cell_column = _first_existing(four_g_mapping, ["Local Cell ID", "Local_Cell_ID"])
    vendor_column = _first_existing(four_g_mapping, ["OP/ Vendor", "OP_Vendor", "Vendor"])
    if four_g_mapping.empty or not enodeb_column or not local_cell_column or not vendor_column:
        raise ValueError("The selected VFUK mapping must contain the 4G sheet with eNodeB ID, Local Cell ID and OP/ Vendor columns.")
    lookup: dict[str, str] = {}
    for enodeb, local_cell, vendor in four_g_mapping[[enodeb_column, local_cell_column, vendor_column]].itertuples(index=False):
        enodeb_id = _integer_cell_component(enodeb)
        local_cell_id = _integer_cell_component(local_cell)
        vendor_text = str(vendor).strip()
        if enodeb_id is None or local_cell_id is None or not vendor_text or vendor_text.lower() == "nan":
            continue
        # Equivalent to Excel: HEX2DEC(DEC2HEX(eNodeB ID, 5) & DEC2HEX(Local Cell ID, 2)).
        if not 0 <= enodeb_id <= 0xFFFFF or not 0 <= local_cell_id <= 0xFF:
            continue
        lookup[str((enodeb_id << 8) | local_cell_id)] = vendor_text
    return lookup


def enrich_multivendor(df: pd.DataFrame, vodafone_mapping: pd.DataFrame, three_mapping: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    operator_column = _first_existing(result, ["operator", "Operator"])
    cell_column = _first_existing(result, ["Cell_ID_A", "Cell_IDs_A", "Cell_ID"])
    if not operator_column or not cell_column:
        raise ValueError("The selected CDR must contain Operator and one of Cell_ID_A, Cell_IDs_A or Cell_ID for multivendor reporting.")
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


def _column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    return _first_existing(frame, candidates)


def _period_column(frame: pd.DataFrame) -> str | None:
    return _column(frame, ("Campaign", "period", "Period", "Quarter"))


def _group_column(frame: pd.DataFrame, multivendor: bool) -> str | None:
    return "report_vendor" if multivendor and "report_vendor" in frame.columns else _column(frame, ("Operator", "operator"))


def _matches(frame: pd.DataFrame, column: str | None, tokens: tuple[str, ...] | None) -> pd.Series:
    if not column or not tokens:
        return pd.Series(True, index=frame.index)
    pattern = "|".join(re.escape(token) for token in tokens)
    return frame[column].astype(str).str.contains(pattern, case=False, na=False, regex=True)


def _source_for_spec(frames: dict[str, pd.DataFrame], spec: dict, multivendor: bool) -> tuple[pd.DataFrame, str | None, str | None]:
    frame = frames[spec["source"]].copy()
    session_column = _column(frame, ("Session_Type", "session_type", "Test_Name", "Test_Type"))
    test_column = _column(frame, ("Test_Name", "test_name", "Type_of_Test", "Test_Type"))
    direction_column = _column(frame, ("Direction", "direction", "Call_Direction"))
    operator_column = _group_column(frame, multivendor)
    mask = _matches(frame, session_column, spec.get("sessions"))
    mask &= _matches(frame, test_column, spec.get("tests"))
    mask &= _matches(frame, direction_column, spec.get("directions"))
    if spec.get("operators"):
        mask &= _matches(frame, operator_column, spec["operators"])
    if spec.get("city_scope"):
        city_column = _column(frame, ("city", "City", "G_Level_1", "G_Level_2"))
        mask &= _matches(frame, city_column, (spec["city_scope"],))
    return frame.loc[mask].copy(), operator_column, _period_column(frame)


def _metric_column(frame: pd.DataFrame, spec: dict) -> str | None:
    return _column(frame, spec.get("metric", ()))


def _colour(label: object, index: int = 0) -> str:
    normalized = str(label).strip().casefold()
    for token, colour in OPERATOR_COLORS.items():
        if token in normalized:
            return colour
    return ("#4E79A7", "#F28E2B", "#B07AA1", "#E15759", "#59A14F", "#76B7B2")[index % 6]


def _canvas(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 24), title, fill="#23384A", font=_font(28, True))
    return image, draw


def _empty_chart(title: str) -> BytesIO:
    image, draw = _canvas(title)
    draw.text((50, 440), "No valid samples for this KPI and technology filter", fill="#61727D", font=_font(24))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _render_status_100(title: str, frame: pd.DataFrame, group: str | None, period: str | None, quality: bool = False, threshold: float = 1.6, metric: str | None = None) -> BytesIO:
    if frame.empty or not group or not period:
        return _empty_chart(title)
    image, draw = _canvas(title)
    state_column = metric if quality else _column(frame, ("Call_Status", "Test_Result", "status"))
    if not state_column:
        return _empty_chart(title)
    states = ("< 1.6", "≥ 1.6") if quality else ("Completed", "Dropped", "Failed")
    colours = ("#E15759", "#59A14F") if quality else ("#4E79A7", "#F28E2B", "#E15759")
    data = frame[[group, period, state_column]].copy()
    if quality:
        data["state"] = pd.to_numeric(data[state_column], errors="coerce").map(lambda value: "< 1.6" if pd.notna(value) and value < threshold else "≥ 1.6")
    else:
        raw = data[state_column].astype(str).str.casefold()
        data["state"] = raw.map(lambda value: "Completed" if any(item in value for item in ("complete", "success", "pass", "ok")) else "Dropped" if "drop" in value else "Failed")
    data = data.dropna(subset=[group, period])
    combos = [(str(g), str(p)) for g, p in data[[group, period]].drop_duplicates().itertuples(index=False)]
    if not combos:
        return _empty_chart(title)
    chart_left, chart_top, chart_width, chart_height = 145, 115, 1300, 640
    bar_width = max(20, min(72, chart_width // max(len(combos) * 2, 1)))
    for i, (g, p) in enumerate(combos):
        subset = data[(data[group].astype(str) == g) & (data[period].astype(str) == p)]
        total = max(len(subset), 1); x = chart_left + i * (chart_width / len(combos)) + 12
        running = 0
        for state, colour in zip(states, colours, strict=True):
            value = len(subset[subset["state"] == state]) / total
            height = value * chart_height
            y = chart_top + chart_height - running - height
            draw.rectangle((x, y, x + bar_width, y + height), fill=colour)
            if value >= .08: draw.text((x + 2, y + height / 2 - 8), f"{value:.0%}", fill="white", font=_font(14, True))
            running += height
        draw.text((x - 4, chart_top + chart_height + 8), p[-8:], fill="#5A6B78", font=_font(13))
    for y in range(0, 101, 20):
        value_y = chart_top + chart_height - (y / 100 * chart_height)
        draw.line((chart_left - 20, value_y, chart_left + chart_width, value_y), fill="#E4E9ED", width=1)
        draw.text((70, value_y - 8), f"{y}%", fill="#62727E", font=_font(14))
    for index, (state, colour) in enumerate(zip(states, colours, strict=True)):
        draw.rectangle((1470, 130 + index * 32, 1490, 150 + index * 32), fill=colour); draw.text((1500, 129 + index * 32), state, fill="#34495A", font=_font(15))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_failure_count(title: str, frame: pd.DataFrame, group: str | None, period: str | None) -> BytesIO:
    if frame.empty or not group:
        return _empty_chart(title)
    status = _column(frame, ("Call_Status", "Test_Result", "status"))
    session = _column(frame, ("Session_Type", "session_type", "Test_Name", "Test_Type"))
    if not status: return _empty_chart(title)
    failed = frame[~frame[status].astype(str).str.contains("complete|success|pass|ok", case=False, na=False)].copy()
    if failed.empty: return _empty_chart(title)
    label = session or group
    fields = [group] if label == group else [group, label]
    counts = failed.groupby(fields, dropna=False).size().reset_index(name="count").head(18)
    image, draw = _canvas(title); maximum = max(int(counts["count"].max()), 1)
    for index, row in counts.iterrows():
        y = 105 + index * 38; width = int(1120 * int(row["count"]) / maximum)
        draw.text((30, y + 6), f"{row[group]} · {row[label]}"[:38], fill="#34495A", font=_font(15))
        draw.rectangle((370, y, 370 + width, y + 24), fill=_colour(row[group], index))
        draw.text((380 + width, y + 4), str(int(row["count"])), fill="#34495A", font=_font(15, True))
    draw.text((370, 820), "# of failed / dropped sessions", fill="#62727E", font=_font(16))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _combine_charts(title: str, charts: list[BytesIO]) -> BytesIO:
    """Place the two chart grammars used together by the supplied templates."""
    usable = [Image.open(chart).convert("RGB") for chart in charts]
    if not usable:
        return _empty_chart(title)
    image, _ = _canvas(title)
    width = image.width // len(usable)
    for index, chart in enumerate(usable):
        chart.thumbnail((width - 18, image.height - 85))
        x = index * width + (width - chart.width) // 2
        image.paste(chart, (x, 80 + (image.height - 80 - chart.height) // 2))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _render_cdf_mean(title: str, frame: pd.DataFrame, group: str | None, period: str | None, metric: str | None) -> BytesIO:
    if frame.empty or not group or not metric: return _empty_chart(title)
    data = frame[[group, metric] + ([period] if period else [])].copy(); data[metric] = pd.to_numeric(data[metric], errors="coerce"); data = data.dropna()
    if data.empty: return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 75, 120, 910, 620
    low, high = float(data[metric].min()), float(data[metric].max()); high = high if high > low else low + 1
    series_column = period if period else group
    labels = [f"{g} · {p}" if period else str(g) for g, p in data[[group, series_column]].drop_duplicates().itertuples(index=False)] if period else [str(v) for v in data[group].drop_duplicates()]
    for index, label in enumerate(labels[:10]):
        if period:
            g, p = label.split(" · ", 1); values = data[(data[group].astype(str) == g) & (data[period].astype(str) == p)][metric].sort_values().tolist()
        else: values = data[data[group].astype(str) == label][metric].sort_values().tolist()
        if not values: continue
        points = [(left + (value - low) / (high - low) * width, top + height - ((n + 1) / len(values)) * height) for n, value in enumerate(values)]
        draw.line(points, fill=_colour(label, index), width=4)
        legend_x = left + (index % 5) * 175
        legend_y = 86 + (index // 5) * 23
        draw.line((legend_x, legend_y + 8, legend_x + 28, legend_y + 8), fill=_colour(label, index), width=4)
        draw.text((legend_x + 35, legend_y), label[:19], fill="#34495A", font=_font(13))
    for tick in range(0, 101, 20):
        y = top + height - tick / 100 * height; draw.line((left, y, left + width, y), fill="#E4E9ED", width=1); draw.text((20, y - 8), f"{tick}%", fill="#62727E", font=_font(13))
    for tick in range(0, 6):
        value = low + (high - low) * tick / 5
        x = left + width * tick / 5
        draw.line((x, top + height, x, top + height + 7), fill="#62727E", width=1)
        draw.text((x - 16, top + height + 7), f"{value:.1f}", fill="#62727E", font=_font(12))
    draw.text((left + width / 2 - 70, top + height + 25), metric.replace("_", " "), fill="#62727E", font=_font(15))
    means = data.groupby(group)[metric].mean().sort_values(); bar_left = 1080; bar_width = 70; max_mean = max(float(means.max()), 1.0)
    for index, (label, value) in enumerate(means.items()):
        height_value = 460 * float(value) / max_mean; x = bar_left + index * 115; y = 680 - height_value
        draw.rectangle((x, y, x + bar_width, 680), fill=_colour(label, index)); draw.text((x, y - 24), f"{float(value):.2f}", fill="#34495A", font=_font(14)); draw.text((x, 692), str(label)[:10], fill="#62727E", font=_font(13))
    draw.text((1080, 730), "Average", fill="#62727E", font=_font(15))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_scatter(title: str, frame: pd.DataFrame, group: str | None, metric: str | None, x_metric: str | None) -> BytesIO:
    if frame.empty or not group or not metric or not x_metric: return _empty_chart(title)
    data = frame[[group, metric, x_metric]].copy(); data[metric] = pd.to_numeric(data[metric], errors="coerce"); data[x_metric] = pd.to_numeric(data[x_metric], errors="coerce"); data = data.dropna()
    if data.empty: return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 130, 120, 1220, 600
    x_low, x_high = float(data[x_metric].min()), float(data[x_metric].max()); y_low, y_high = float(data[metric].min()), float(data[metric].max()); x_high = x_high if x_high > x_low else x_low + 1; y_high = y_high if y_high > y_low else y_low + 1
    for index, (label, subset) in enumerate(data.groupby(group)):
        for x_value, y_value in subset[[x_metric, metric]].itertuples(index=False):
            x = left + (x_value - x_low) / (x_high - x_low) * width; y = top + height - (y_value - y_low) / (y_high - y_low) * height
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=_colour(label, index))
        legend_y = 120 + index * 26
        draw.ellipse((1380, legend_y, 1392, legend_y + 12), fill=_colour(label, index))
        draw.text((1400, legend_y - 2), str(label)[:20], fill="#34495A", font=_font(14))
    for tick in range(0, 6):
        x = left + width * tick / 5; y = top + height - height * tick / 5
        x_value = x_low + (x_high - x_low) * tick / 5; y_value = y_low + (y_high - y_low) * tick / 5
        draw.line((x, top + height, x, top + height + 7), fill="#62727E", width=1)
        draw.line((left - 7, y, left, y), fill="#62727E", width=1)
        draw.text((x - 16, top + height + 7), f"{x_value:.0f}", fill="#62727E", font=_font(12))
        draw.text((75, y - 7), f"{y_value:.1f}", fill="#62727E", font=_font(12))
    draw.text((left + width / 2 - 120, top + height + 28), x_metric.replace("_", " "), fill="#62727E", font=_font(16)); draw.text((40, 95), metric.replace("_", " "), fill="#62727E", font=_font(16))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _chart_for_spec(title: str, frames: dict[str, pd.DataFrame], spec: dict, multivendor: bool) -> BytesIO:
    frame, group, period = _source_for_spec(frames, spec, multivendor); metric = _metric_column(frame, spec)
    if spec["kind"] == "status_100": return _render_status_100(title, frame, group, period)
    if spec["kind"] == "quality_100": return _render_status_100(title, frame, group, period, True, spec.get("threshold", 1.6), metric)
    if spec["kind"] == "failure_count": return _render_failure_count(title, frame, group, period)
    if spec["kind"] == "scatter": return _render_scatter(title, frame, group, metric, _column(frame, spec.get("x_metric", ())))
    if spec["kind"] == "dual_quality_100":
        secondary = {"kind": "quality_100", "threshold": spec.get("threshold", 1.6), **spec["secondary"]}
        other_frame, other_group, other_period = _source_for_spec(frames, secondary, multivendor)
        other_metric = _metric_column(other_frame, secondary)
        return _combine_charts(title, [
            _render_status_100("WhatsApp", frame, group, period, True, spec.get("threshold", 1.6), metric),
            _render_status_100("VoLTE", other_frame, other_group, other_period, True, secondary["threshold"], other_metric),
        ])
    if spec["kind"] == "quality_cdf":
        return _combine_charts(title, [
            _render_status_100("POLQA <1.6 rate", frame, group, period, True, spec.get("threshold", 1.6), metric),
            _render_cdf_mean("POLQA AVG MOS CDF", frame, group, period, metric),
        ])
    if spec["kind"] == "cdf_pair":
        secondary_metric = _column(frame, spec.get("secondary_metric", ()))
        return _combine_charts(title, [
            _render_cdf_mean(metric.replace("_", " ") if metric else title, frame, group, period, metric),
            _render_cdf_mean(secondary_metric.replace("_", " ") if secondary_metric else title, frame, group, period, secondary_metric),
        ])
    if spec["kind"] == "cdf_bucket":
        # The template combines a throughput CDF with a low-rate distribution.
        # The averaged columns are retained as the numerical distribution summary.
        return _render_cdf_mean(title, frame, group, period, metric)
    return _render_cdf_mean(title, frame, group, period, metric)


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
    chart_specs = REPORT_CHART_SPECS[technology]
    for number, slide in enumerate(presentation.slides, start=1):
        _clear_commentary(slide)
        spec = chart_specs.get(number)
        if not spec:
            continue
        title = next((shape.text.strip() for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip()), "CDR KPI")
        chart = _chart_for_spec(title, frames, spec, multivendor)
        chart_frame = _combined_frame(_chart_frames(slide))
        if not chart_frame:
            chart_frame = (Inches(0.55), Inches(1.65), Inches(6.15), Inches(3.75))
        slide.shapes.add_picture(chart, *chart_frame)
    presentation.save(destination)
    return destination
