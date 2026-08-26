"""NetCheck CDR report preparation and template-backed PPT rendering."""

from __future__ import annotations

import csv
import io
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches, Pt


TEMPLATE_NAMES = {
    "nsa": "Template_CDR_NSA_analysis.pptx",
    "sa": "Template_CDR_SA_analysis.pptx",
}
CDR_REPORT_VERSION = "2026-08-26-v6"
REPORTING_KINDS = {"data", "voice", "speech"}
COMMENT_HINTS = ("having ", "observed", "shows ", "similar performance", "worse ", "improvement", "degradation", "gap ")
CATALOG_HEADERS = ("Slide", "Slide tittle", "Slide Subtittle", "CDR source", "KPI", "Chart type", "Filters", "Grouping")
CATALOG_SOURCE_KINDS = {"cdr-data": "data", "cdr-voice": "voice", "cdr-speech": "speech"}
CHART_TYPES = {
    "100% stacked vertical bars", "count stacked horizontal bars", "cdf line", "scatter", "table",
    "distribution stacked vertical bars", "threshold stacked vertical bars", "average vertical bars", "median vertical bars",
}
PRESERVED_CHART_TYPES = {
    "preserved cover", "preserved agenda", "preserved section divider", "preserved summary",
    "preserved tracker", "preserved conclusions", "preserved closing slide", "not automated",
}
FILTER_OPERATORS = ("CONTAINS", "IN", ">=", "<=", "!=", "=", ">", "<")


@dataclass(frozen=True)
class FilterCondition:
    column: str
    operator: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class GroupingSpec:
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class CatalogEntry:
    slide: int
    slide_title: str
    slide_subtitle: str
    cdr_source: str
    kpi: str
    chart_type: str
    filters: str
    grouping: str

    @property
    def source_kind(self) -> str | None:
        return CATALOG_SOURCE_KINDS.get(self.cdr_source.strip().casefold())


def parse_catalog_filters(value: str) -> tuple[FilterCondition, ...]:
    """Parse `Column OP value; ...` syntax without needing a particular CDR schema."""
    if not value.strip():
        return ()
    conditions: list[FilterCondition] = []
    for clause in (part.strip() for part in value.split(";") if part.strip()):
        match = re.fullmatch(r"(.+?)\s+(CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)", clause, flags=re.I)
        if not match:
            # Compatibility for the initial supplied catalogues. New catalogues must use the syntax above.
            continue
        column, operator, raw_values = (part.strip() for part in match.groups())
        # Existing quality-ratio rows describe both output states as "LQ < 1.6 vs ≥ 1.6".
        # That is chart metadata, not a source-row filter.
        if operator in {">", ">=", "<", "<="} and re.search(r"\bvs\b", raw_values, flags=re.I):
            continue
        if not column:
            raise ValueError(f"Invalid filter '{clause}': a column name is required.")
        if operator.upper() == "IN":
            if not raw_values.startswith("(") or not raw_values.endswith(")"):
                raise ValueError(f"Invalid filter '{clause}': IN values must use parentheses.")
            values = tuple(item.strip() for item in raw_values[1:-1].split(",") if item.strip())
        else:
            values = (raw_values,)
        if not values:
            raise ValueError(f"Invalid filter '{clause}': a value is required.")
        conditions.append(FilterCondition(column, operator.upper(), values))
    return tuple(conditions)


def parse_catalog_grouping(value: str) -> GroupingSpec:
    if not value.strip():
        return GroupingSpec(())
    dimensions = tuple(part.strip() for part in re.split(r"\s*(?:×|x)\s*", value, flags=re.I) if part.strip())
    if not dimensions:
        raise ValueError("Grouping must contain at least one dimension.")
    return GroupingSpec(dimensions)


def parse_catalog_csv(content: bytes | str, technology: str) -> list[CatalogEntry]:
    """Validate the editable report-catalogue CSV and return its chart rows."""
    if technology not in TEMPLATE_NAMES:
        raise ValueError("Catalog technology must be NSA or SA.")
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The report catalogue must be a UTF-8 CSV file.") from exc
    else:
        text = content
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != CATALOG_HEADERS:
        raise ValueError("The report catalogue must use exactly these columns: " + ", ".join(CATALOG_HEADERS))
    entries: list[CatalogEntry] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            slide = int((row.get("Slide") or "").strip())
        except ValueError as exc:
            raise ValueError(f"Catalog row {line_number} has an invalid Slide value.") from exc
        if slide < 1:
            raise ValueError(f"Catalog row {line_number} must use a positive slide number.")
        entry = CatalogEntry(
            slide=slide,
            slide_title=(row.get("Slide tittle") or "").strip().replace("\\n", "\n"),
            slide_subtitle=(row.get("Slide Subtittle") or "").strip().replace("\\n", "\n"),
            cdr_source=(row.get("CDR source") or "").strip(),
            kpi=(row.get("KPI") or "").strip(),
            chart_type=(row.get("Chart type") or "").strip(),
            filters=(row.get("Filters") or "").strip(),
            grouping=(row.get("Grouping") or "").strip(),
        )
        if entry.source_kind and not entry.slide_title:
            raise ValueError(f"Catalog row {line_number} requires Slide tittle for a CDR source.")
        if entry.cdr_source and entry.cdr_source.casefold() not in CATALOG_SOURCE_KINDS:
            raise ValueError(f"Catalog row {line_number} has unsupported CDR source '{entry.cdr_source}'.")
        if entry.source_kind and (not entry.kpi or not entry.chart_type):
            raise ValueError(f"Catalog row {line_number} requires KPI and Chart type for a CDR source.")
        if entry.source_kind and entry.chart_type.casefold() not in CHART_TYPES:
            raise ValueError(f"Catalog row {line_number} has unsupported Chart type '{entry.chart_type}'.")
        if entry.source_kind and not entry.grouping:
            raise ValueError(f"Catalog row {line_number} requires Grouping for a CDR source.")
        try:
            parse_catalog_filters(entry.filters)
            parse_catalog_grouping(entry.grouping)
        except ValueError as exc:
            raise ValueError(f"Catalog row {line_number}: {exc}") from exc
        entries.append(entry)
    if not entries:
        raise ValueError("The report catalogue does not contain any rows.")
    return entries


def load_catalog_csv(path: Path, technology: str) -> list[CatalogEntry]:
    return parse_catalog_csv(path.read_bytes(), technology)


def active_catalog_path(catalog_dir: Path, fallback_catalog: Path, technology: str) -> Path:
    imported = catalog_dir / f"{technology}-slide-catalogue.csv"
    return imported if imported.exists() else fallback_catalog


def catalogue_markdown(entries: list[CatalogEntry], technology: str) -> str:
    heading = "NSA" if technology == "nsa" else "SA"
    lines = [f"### {heading} template", "", "| " + " | ".join(CATALOG_HEADERS) + " |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for entry in entries:
        values = (str(entry.slide), entry.slide_title, entry.slide_subtitle or "—", entry.cdr_source or "—", entry.kpi or "—", entry.chart_type or "—", entry.filters or "—", entry.grouping or "—")
        lines.append("| " + " | ".join(value.replace("|", "\\|").replace("\n", "<br>") for value in values) + " |")
    return "\n".join(lines)


def update_catalogue_document(document: Path, nsa_entries: list[CatalogEntry], sa_entries: list[CatalogEntry]) -> None:
    start = "<!-- SLIDE_CATALOGUE:START -->"
    end = "<!-- SLIDE_CATALOGUE:END -->"
    content = document.read_text(encoding="utf-8")
    if start not in content or end not in content:
        raise ValueError("The PowerPoint reporting help document is missing its slide-catalogue markers.")
    block = "\n".join((start, "", "Export the active NSA or SA catalogue from Admin before editing it. The tables below always reflect the active CSV files under `assets/ppt-slides-catalog/`.", "", catalogue_markdown(nsa_entries, "nsa"), "", catalogue_markdown(sa_entries, "sa"), "", end))
    document.write_text(re.sub(re.escape(start) + r".*?" + re.escape(end), block, content, flags=re.S), encoding="utf-8")

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


def _normalise_catalog_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _catalog_column(frame: pd.DataFrame, name: str, multivendor: bool, metric: str | None = None, bucket_edges: list[float] | None = None) -> str | None:
    """Resolve a catalogue field name against a source column or supported semantic dimension."""
    normalized = _normalise_catalog_name(name)
    if normalized == "operator":
        return _group_column(frame, multivendor)
    aliases = {
        "campaign": ("Campaign", "period", "Period", "Quarter"),
        "city": ("City", "city", "G_Level_1", "G_Level_2"),
        "callfamily": ("Call_Family", "Session_Type", "Test_Name", "Test_Type"),
        "testfamily": ("Test_Family", "Test_Name", "Test_Type", "Type_of_Test"),
        "failuretechnology": ("Failure_Technology",),
        "failurecategory": ("Failure_Category",),
        "n rband": ("NR_Band", "NR band", "Band_NR"),
        "nrband": ("NR_Band", "NR band", "Band_NR"),
        "lteband": ("LTE_Band", "4G_Band", "Band_LTE"),
        "radioband": ("NR_Band", "LTE_Band", "Band", "Radio_Band"),
    }
    if normalized in {"ratebucket", "valuebucket"}:
        if not metric:
            return None
        numeric = pd.to_numeric(frame[metric], errors="coerce")
        edges = bucket_edges or [1, 5, 10, 25, 50]
        labels = [f"<{edges[0]:g}"] + [f"{low:g}-{high:g}" for low, high in zip(edges, edges[1:])] + [f"{edges[-1]:g}+"]
        frame["__catalog_rate_bucket"] = pd.cut(numeric, bins=[float("-inf"), *edges, float("inf")], labels=labels, right=False).astype("string")
        return "__catalog_rate_bucket"
    candidate = _column(frame, aliases.get(normalized, (name,)))
    if candidate:
        return candidate
    for column in frame.columns:
        if _normalise_catalog_name(str(column)) == normalized:
            return str(column)
    return None


def _apply_catalog_filters(frame: pd.DataFrame, entry: CatalogEntry, multivendor: bool, metric: str | None) -> pd.DataFrame:
    result = frame.copy()
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) in {"threshold", "buckets"}:
            continue
        column = _catalog_column(result, condition.column, multivendor, metric)
        if not column:
            raise ValueError(f"Slide {entry.slide}: filter column '{condition.column}' does not exist in {entry.cdr_source}.")
        series = result[column]
        if condition.operator in {">", ">=", "<", "<=", "=", "!="}:
            target = condition.values[0]
            numeric = pd.to_numeric(series, errors="coerce")
            target_number = pd.to_numeric(pd.Series([target]), errors="coerce").iloc[0]
            if pd.notna(target_number):
                comparison = {">": numeric > target_number, ">=": numeric >= target_number, "<": numeric < target_number, "<=": numeric <= target_number, "=": numeric == target_number, "!=": numeric != target_number}[condition.operator]
            else:
                comparison = {"=": series.astype(str).str.casefold() == target.casefold(), "!=": series.astype(str).str.casefold() != target.casefold()}.get(condition.operator)
                if comparison is None:
                    raise ValueError(f"Slide {entry.slide}: '{condition.operator}' requires a numeric value for '{condition.column}'.")
        elif condition.operator == "CONTAINS":
            comparison = series.astype(str).str.contains(condition.values[0], case=False, na=False, regex=False)
        else:  # IN
            accepted = {item.casefold() for item in condition.values}
            comparison = series.astype(str).str.casefold().isin(accepted)
        result = result.loc[comparison].copy()
    return result


def _catalog_threshold(entry: CatalogEntry) -> float:
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) == "threshold":
            try:
                return float(condition.values[0])
            except ValueError as exc:
                raise ValueError(f"Slide {entry.slide}: Threshold must be numeric.") from exc
    legacy = re.search(r"(?:<|<=)\s*([0-9]+(?:\.[0-9]+)?)\s+vs", entry.filters, flags=re.I)
    return float(legacy.group(1)) if legacy else 1.6


def _catalog_bucket_edges(entry: CatalogEntry) -> list[float] | None:
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) == "buckets":
            try:
                edges = [float(value.strip()) for value in condition.values[0].split(",")]
            except ValueError as exc:
                raise ValueError(f"Slide {entry.slide}: Buckets must be a comma-separated numeric list.") from exc
            if len(edges) < 1 or edges != sorted(set(edges)):
                raise ValueError(f"Slide {entry.slide}: Buckets must be unique ascending values.")
            return edges
    return None


def _apply_catalog_grouping(frame: pd.DataFrame, entry: CatalogEntry, multivendor: bool, metric: str | None) -> tuple[pd.DataFrame, str, str]:
    spec = parse_catalog_grouping(entry.grouping)
    resolved: list[str] = []
    bucket_edges = _catalog_bucket_edges(entry)
    for dimension in spec.dimensions:
        column = _catalog_column(frame, dimension, multivendor, metric, bucket_edges)
        if not column:
            raise ValueError(f"Slide {entry.slide}: grouping dimension '{dimension}' does not exist in {entry.cdr_source}.")
        resolved.append(column)
    # The first level is the category axis; all following levels form the comparison series.
    primary = "__catalog_primary"
    series = "__catalog_series"
    frame[primary] = frame[resolved[0]].fillna("(blank)").astype(str)
    if len(resolved) == 1:
        frame[series] = frame[primary]
    else:
        series_columns = resolved[1:-1] if len(resolved) >= 3 else resolved[1:]
        frame[series] = frame[series_columns].fillna("(blank)").astype(str).agg(" · ".join, axis=1)
    if len(resolved) >= 3:
        frame["__catalog_stack"] = frame[resolved[-1]].fillna("(blank)").astype(str)
    return frame, primary, series


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
    label = period or session or group
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


def _render_stacked_distribution(title: str, frame: pd.DataFrame, group: str | None, series: str | None, stack: str) -> BytesIO:
    if frame.empty or not group or not series or stack not in frame.columns:
        return _empty_chart(title)
    data = frame[[group, series, stack]].dropna()
    combinations = list(data[[group, series]].drop_duplicates().itertuples(index=False, name=None))
    buckets = list(data[stack].drop_duplicates())
    if not combinations or not buckets:
        return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 125, 125, 1260, 610
    bar_width = max(20, min(70, width // max(len(combinations) * 2, 1)))
    for index, (category, series_value) in enumerate(combinations):
        subset = data[(data[group] == category) & (data[series] == series_value)]
        total = max(len(subset), 1); x = left + index * (width / len(combinations)) + 10; running = 0
        for bucket_index, bucket in enumerate(buckets):
            value = len(subset[subset[stack] == bucket]) / total; segment = value * height; y = top + height - running - segment
            draw.rectangle((x, y, x + bar_width, y + segment), fill=_colour(bucket, bucket_index))
            running += segment
        draw.text((x - 4, top + height + 10), str(series_value)[:12], fill="#5A6B78", font=_font(12))
    for index, bucket in enumerate(buckets[:8]):
        x = left + index * 150
        draw.rectangle((x, 82, x + 20, 100), fill=_colour(bucket, index)); draw.text((x + 27, 82), str(bucket), fill="#34495A", font=_font(13))
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


def _render_mean_column(title: str, frame: pd.DataFrame, group: str | None, metric: str | None, aggregation: str = "mean") -> BytesIO:
    if frame.empty or not group or not metric:
        return _empty_chart(title)
    data = frame[[group, metric]].copy()
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    aggregate = data.dropna().groupby(group)[metric]
    means = (aggregate.median() if aggregation == "median" else aggregate.mean()).sort_values()
    if means.empty:
        return _empty_chart(title)
    image, draw = _canvas(title)
    left, baseline, maximum = 120, 730, max(float(means.max()), 1.0)
    width = min(150, max(54, 1000 // len(means)))
    for index, (label, value) in enumerate(means.items()):
        height = 520 * float(value) / maximum
        x = left + index * (width + 55)
        draw.rectangle((x, baseline - height, x + width, baseline), fill=_colour(label, index))
        draw.text((x, baseline - height - 28), f"{float(value):.2f}", fill="#34495A", font=_font(15))
        draw.text((x, baseline + 12), str(label)[:16], fill="#62727E", font=_font(14))
    draw.text((left, 780), metric.replace("_", " "), fill="#62727E", font=_font(16))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _render_table(title: str, frame: pd.DataFrame, group: str | None, series: str | None, metric: str | None) -> BytesIO:
    """Render a compact mean-value table grouped exactly as declared in the catalogue."""
    if frame.empty or not group or not metric:
        return _empty_chart(title)
    data = frame[[group, series, metric]].copy() if series else frame[[group, metric]].copy()
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.dropna(subset=[metric])
    if data.empty:
        return _empty_chart(title)
    if series and series != group:
        table = data.pivot_table(index=group, columns=series, values=metric, aggfunc="mean")
    else:
        table = data.groupby(group)[metric].mean().to_frame("Value")
    image, draw = _canvas(title)
    headers = [str(table.index.name or "Category")] + [str(value) for value in table.columns]
    rows = [(str(index), *["" if pd.isna(value) else f"{float(value):.2f}" for value in values]) for index, values in table.head(18).iterrows()]
    col_width = min(310, 1450 // max(len(headers), 1)); row_height = 34; left, top = 55, 115
    for col, header in enumerate(headers):
        x = left + col * col_width
        draw.rectangle((x, top, x + col_width, top + row_height), fill="#23384A")
        draw.text((x + 8, top + 8), header[:28], fill="white", font=_font(14, True))
    for row_index, row in enumerate(rows):
        y = top + (row_index + 1) * row_height
        fill = "#F4F7F9" if row_index % 2 == 0 else "#FFFFFF"
        for col, value in enumerate(row):
            x = left + col * col_width
            draw.rectangle((x, y, x + col_width, y + row_height), fill=fill, outline="#D9E1E6")
            draw.text((x + 8, y + 8), str(value)[:28], fill="#34495A", font=_font(13))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _catalog_tokens(filters: str, keyword: str) -> tuple[str, ...]:
    text = filters.casefold()
    if keyword == "session":
        return tuple(token for token in ("volte", "multirab", "whatsapp", "classic", "call") if token in text)
    if keyword == "test":
        return tuple(token for token in ("fdfs", "fdtt", "interactivity", "brows", "http", "youtube", "video") if token in text)
    if keyword == "direction":
        return tuple(token for token in ("dl", "ul") if re.search(rf"\b{token}\b", text))
    return ()


def _catalog_spec(entry: CatalogEntry) -> dict:
    filters = entry.filters.casefold()
    chart_type = entry.chart_type.casefold()
    metric_parts = tuple(part.strip(" `") for part in re.split(r"\s+vs\s+", entry.kpi, flags=re.I) if part.strip())
    spec: dict = {"source": entry.source_kind, "metric": metric_parts[:1] or (entry.kpi,)}
    sessions, tests, directions = _catalog_tokens(entry.filters, "session"), _catalog_tokens(entry.filters, "test"), _catalog_tokens(entry.filters, "direction")
    if sessions:
        spec["sessions"] = sessions
    if tests:
        spec["tests"] = tests
    if directions:
        spec["directions"] = directions
    if "vodafone" in filters:
        spec["operators"] = ("vodafone",)
    elif "three uk" in filters or "3uk" in filters:
        spec["operators"] = ("three", "3 uk", "3")
    if "london" in filters:
        spec["city_scope"] = "london"
    if "scatter" in chart_type:
        spec["kind"] = "scatter"
        spec["x_metric"] = metric_parts[1:] or ("Playing_RSRP_NR_Avg", "NR_RSRP_Avg")
    elif "failed" in filters or "failure" in entry.slide_title.casefold():
        spec["kind"] = "failure_count"
    elif "100%" in chart_type or chart_type == "threshold stacked vertical bars":
        spec["kind"] = "quality_100" if chart_type == "threshold stacked vertical bars" or any(token in entry.kpi.casefold() for token in ("lq", "polqa")) else "status_100"
        if spec["kind"] == "quality_100":
            spec["threshold"] = _catalog_threshold(entry)
    else:
        spec["kind"] = "cdf_mean"
    return spec


def _chart_for_catalog_entry(entry: CatalogEntry, frames: dict[str, pd.DataFrame], multivendor: bool) -> BytesIO:
    spec = _catalog_spec(entry)
    frame, group, period = _source_for_spec(frames, spec, multivendor)
    metric = _metric_column(frame, spec)
    try:
        frame = _apply_catalog_filters(frame, entry, multivendor, metric)
        frame, group, period = _apply_catalog_grouping(frame, entry, multivendor, metric)
    except ValueError:
        # A partial CDR upload should leave only the affected chart empty, not fail the report.
        return _empty_chart(entry.slide_title)
    chart_type = entry.chart_type.casefold()
    if chart_type != "distribution stacked vertical bars" and "__catalog_stack" in frame.columns:
        frame[period] = frame[period].astype(str) + " · " + frame["__catalog_stack"].astype(str)
    if spec["kind"] == "status_100":
        return _render_status_100(entry.slide_title, frame, group, period)
    if spec["kind"] == "quality_100":
        return _render_status_100(entry.slide_title, frame, group, period, True, spec.get("threshold", 1.6), metric)
    if spec["kind"] == "failure_count":
        return _render_failure_count(entry.slide_title, frame, group, period)
    if chart_type == "distribution stacked vertical bars":
        return _render_stacked_distribution(entry.slide_title, frame, group, period, "__catalog_stack")
    # Non-stacked visuals have one visual series per complete grouping combination.
    frame["__catalog_label"] = frame[group].fillna("(blank)").astype(str) + " · " + frame[period].fillna("(blank)").astype(str)
    if spec["kind"] == "scatter":
        return _render_scatter(entry.slide_title, frame, "__catalog_label", metric, _column(frame, spec.get("x_metric", ())))
    if chart_type == "table":
        return _render_table(entry.slide_title, frame, group, period, metric)
    if "vertical bars" in chart_type:
        return _render_mean_column(entry.slide_title, frame, "__catalog_label", metric, aggregation="median" if chart_type == "median vertical bars" else "mean")
    return _render_cdf_mean(entry.slide_title, frame, group, period, metric)


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


def _set_slide_header(slide, title: str, subtitle: str) -> None:
    title_shape = next(
        (
            shape for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
            and getattr(shape, "is_placeholder", False)
            and shape.placeholder_format.type in {1, 3}
        ),
        None,
    )
    if title_shape is None:
        title_shape = next(
            (shape for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.top < Inches(1.2)),
            None,
        )
    if title_shape is not None and title:
        title_shape.text = title
    existing_subtitle = next((shape for shape in slide.shapes if shape.name == "catalogue-subtitle"), None)
    if existing_subtitle is not None:
        existing_subtitle._element.getparent().remove(existing_subtitle._element)
    if subtitle:
        top = (title_shape.top + title_shape.height) if title_shape is not None else Inches(0.8)
        text_box = slide.shapes.add_textbox(Inches(0.55), top, Inches(11.6), Inches(0.36))
        text_box.name = "catalogue-subtitle"
        paragraph = text_box.text_frame.paragraphs[0]
        paragraph.text = subtitle
        paragraph.font.size = Pt(13)
        paragraph.font.italic = True


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


def _master_placeholder_frames(presentation: Presentation, chart_count: int) -> list[tuple[int, int, int, int]]:
    """Read the bundled master layouts as the placement contract for chart images."""
    if not 1 <= chart_count <= 4:
        return []
    expected = f"title and {chart_count} {'column' if chart_count == 1 else 'columns'}"
    for layout in presentation.slide_layouts:
        if layout.name.strip().casefold() != expected:
            continue
        frames = [
            (shape.left, shape.top, shape.width, shape.height)
            for shape in layout.placeholders
            if shape.placeholder_format.type == 7  # PP_PLACEHOLDER_TYPE.OBJECT
        ]
        if len(frames) >= chart_count:
            return sorted(frames, key=lambda frame: (frame[1], frame[0]))[:chart_count]
    return []


def render_cdr_report(destination: Path, template: Path, frames: dict[str, pd.DataFrame], technology: str,
                      multivendor: bool, catalog: list[CatalogEntry] | None = None) -> Path:
    if not template.exists():
        raise FileNotFoundError(f"Reporting template not found: {template.name}")
    shutil.copyfile(template, destination)
    presentation = Presentation(destination)
    chart_specs = REPORT_CHART_SPECS[technology]
    catalog_by_slide: dict[int, list[CatalogEntry]] = defaultdict(list)
    catalog_headers: dict[int, CatalogEntry] = {}
    for entry in catalog or []:
        catalog_headers.setdefault(entry.slide, entry)
        if entry.source_kind:
            catalog_by_slide[entry.slide].append(entry)
    for number, slide in enumerate(presentation.slides, start=1):
        _clear_commentary(slide)
        if number in catalog_headers:
            header = catalog_headers[number]
            _set_slide_header(slide, header.slide_title, header.slide_subtitle)
        catalog_entries = catalog_by_slide.get(number, [])
        if catalog_entries:
            removed_frames = _chart_frames(slide)
            placement_frames = _master_placeholder_frames(presentation, len(catalog_entries)) or removed_frames
            if len(placement_frames) < len(catalog_entries):
                combined = _combined_frame(removed_frames) or (Inches(0.55), Inches(1.65), Inches(6.15), Inches(3.75))
                placement_frames = [combined] * len(catalog_entries)
            for entry, placement in zip(catalog_entries, placement_frames, strict=True):
                slide.shapes.add_picture(_chart_for_catalog_entry(entry, frames, multivendor), *placement)
            continue
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
