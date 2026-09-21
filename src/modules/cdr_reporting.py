"""NetCheck CDR report preparation and template-backed PPT rendering."""

from __future__ import annotations

import atexit
import base64
import csv
import gc
import heapq
import io
import json
import math
import os
import re
import ssl
import subprocess
import threading
import unicodedata
from urllib.error import URLError
from urllib.request import Request, urlopen
from collections import defaultdict
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from io import BytesIO
from itertools import product
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pandas as pd
from src.modules.column_names import MAIN_CDR_FIELDS, column_identity, compact_campaign_value, resolve_column_name, vendor_only_value
import certifi
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Inches, Pt

from src.utils.fonts import load_image_font
from src.config import settings


TEMPLATE_NAMES = {
    "nsa": "Template_CDR_analysis.pptx",
    "sa": "Template_CDR_analysis.pptx",
}
CDR_REPORT_VERSION = "2026-09-21-v12"
REPORTING_KINDS = {"data", "voice", "speech"}
COMMENT_HINTS = ("having ", "observed", "shows ", "similar performance", "worse ", "improvement", "degradation", "gap ")
VISUAL_CATALOG_HEADERS = ("Slide", "Slide Tittle", "Slide Subtittle", "Layout", "Chart Tittle", "CDR source", "KPI", "Chart type", "Filters", "Rows Aggregation", "Column Aggregation", "Legend", "Legend Position", "Label", "Axis X Range", "Axis Y Range")
CATALOG_HEADERS = (*VISUAL_CATALOG_HEADERS, "Exclude Null/Empty", "Exclude Zero")
# Templates created before configurable visual settings remain valid and
# acquire empty Label/axis cells the next time they are saved in the editor.
RANGELESS_CATALOG_HEADERS = CATALOG_HEADERS[:13]
# Import the two immediately preceding schemas too, so existing templates remain
# usable after the aggregation columns were renamed and the legend was repositioned.
PREVIOUS_CATALOG_HEADERS = ("Slide", "Slide tittle", "Slide Subtittle", "Layout", "Chart Tittle", "CDR source", "KPI", "Chart type", "Legend", "Filters", "Grouping_Rows", "Grouping_Columns", "Legend Position")
OLDER_CATALOG_HEADERS = ("Slide", "Slide tittle", "Slide Subtittle", "Layout", "Chart Tittle", "CDR source", "KPI", "Chart type", "Legend", "Filters", "Grouping_Rows", "Grouping_Columns")
LEGACY_ROWS_COLUMNS_HEADERS = ("Slide", "Slide tittle", "Slide Subtittle", "Layout", "CDR source", "KPI", "Chart type", "Filters", "Grouping_Rows", "Grouping_Columns")
LEGACY_CATALOG_HEADERS = ("Slide", "Slide tittle", "Slide Subtittle", "Layout", "CDR source", "KPI", "Chart type", "Filters", "Grouping")
CATALOG_SOURCE_KINDS = {"cdr-data": "data", "cdr-voice": "voice", "cdr-speech": "speech"}
CHART_TYPES = {
    "100% stacked vertical bars", "count stacked horizontal bars", "cdf line", "multi kpi cdf lines", "scatter", "table", "dynamic table",
    "distribution stacked vertical bars", "threshold stacked vertical bars", "average vertical bars", "median vertical bars", "map",
}
BAR_CHART_TYPES = {
    "100% stacked vertical bars", "count stacked horizontal bars",
    "distribution stacked vertical bars", "threshold stacked vertical bars",
    "average vertical bars", "median vertical bars",
}
STRUCTURAL_SLIDE_TYPES = {"title slide", "transition slide"}
PRESERVED_CHART_TYPES = {"not automated (preserve)"}
FILTER_OPERATORS = ("CONTAINS", "NOT CONTAINS", "IN", "NOT IN", ">=", "<=", "!=", "=", ">", "<")
# The rendered CDF is 1,165 pixels wide. More than one hit-test vertex per
# ten pixels does not improve pointer precision, but greatly inflates sidecars.
MAX_CDF_HOVER_TARGETS_PER_SERIES = 120
# Increment when renderer coordinates or semantic hit-area geometry changes.
HOVER_TARGETS_VERSION = 3
OSM_TILE_SIZE = 256
# A Map PNG is 1260 pixels wide. Starting at a street-level zoom keeps labels
# and roads crisp after the final resize while still bounding a cold cache.
OSM_TILE_MAX_COUNT = 48
OSM_TILE_MAX_ZOOM = 18
OSM_TILE_CACHE_DIR = settings.data_dir / '.map-tiles-cache' / 'openstreetmap'
OSM_TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
REPORT_CHART_RENDERER_ENV = "DASHBOARD_ANALYTIC_REPORT_CHART_RENDERER"
_DASHBOARD_CANVAS_RENDERER = None
_DASHBOARD_CANVAS_RENDERER_LOCK = threading.RLock()


class _DashboardCanvasRenderer:
    """Keep one headless Chromium canvas alive for repeated report PNG exports."""

    def __init__(self) -> None:
        script = Path(__file__).with_name("dashboard_canvas_renderer.mjs")
        self.process = subprocess.Popen(
            ["node", str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        ready_line = self.process.stdout.readline() if self.process.stdout else ""
        ready = json.loads(ready_line or "{}")
        if not ready.get("ready"):
            self.close()
            raise RuntimeError(ready.get("error") or "Unable to start the Dashboard Canvas renderer.")
        self.request_id = 0

    def render(
        self, payload: dict[str, object], *, width: int = 1600, height: int = 900,
    ) -> tuple[bytes, list[dict[str, object]]]:
        if not self.process.stdin or not self.process.stdout or self.process.poll() is not None:
            raise RuntimeError("The Dashboard Canvas renderer is not running.")
        self.request_id += 1
        self.process.stdin.write(json.dumps({
            "id": self.request_id, "payload": payload, "width": width, "height": height,
        }, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline() or "{}")
        if response.get("error"):
            raise RuntimeError(response["error"])
        if response.get("id") != self.request_id or not response.get("png"):
            raise RuntimeError("The Dashboard Canvas renderer returned an invalid response.")
        hits = response.get("hits")
        return base64.b64decode(response["png"]), hits if isinstance(hits, list) else []

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is None or process.poll() is not None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()


def _render_dashboard_payload(
    payload: dict[str, object], *, width: int = 1600, height: int = 900,
) -> tuple[bytes, list[dict[str, object]]]:
    global _DASHBOARD_CANVAS_RENDERER
    with _DASHBOARD_CANVAS_RENDERER_LOCK:
        if _DASHBOARD_CANVAS_RENDERER is None or _DASHBOARD_CANVAS_RENDERER.process.poll() is not None:
            _DASHBOARD_CANVAS_RENDERER = _DashboardCanvasRenderer()
        return _DASHBOARD_CANVAS_RENDERER.render(payload, width=width, height=height)


def _render_dashboard_payload_png(payload: dict[str, object]) -> bytes:
    return _render_dashboard_payload(payload)[0]


def _close_dashboard_canvas_renderer() -> None:
    global _DASHBOARD_CANVAS_RENDERER
    with _DASHBOARD_CANVAS_RENDERER_LOCK:
        if _DASHBOARD_CANVAS_RENDERER is not None:
            _DASHBOARD_CANVAS_RENDERER.close()
            _DASHBOARD_CANVAS_RENDERER = None


def reset_dashboard_canvas_renderer() -> None:
    """Restart the shared renderer after its executable configuration changes."""
    _close_dashboard_canvas_renderer()


atexit.register(_close_dashboard_canvas_renderer)


def report_chart_renderer_name(renderer: str | None = None) -> str:
    """Resolve the shared export painter, with PIL retained as an explicit fallback."""
    selected = (renderer or os.environ.get(REPORT_CHART_RENDERER_ENV, "dashboard-canvas")).strip().casefold()
    aliases = {
        "pil": "pil",
        "legacy": "pil",
        "dashboard": "dashboard-canvas",
        "canvas": "dashboard-canvas",
        "dashboard-canvas": "dashboard-canvas",
    }
    if selected not in aliases:
        raise ValueError(
            f"Unsupported report chart renderer '{selected}'. Expected 'pil' or 'dashboard-canvas'."
        )
    return aliases[selected]


def _dashboard_hits_to_hover_targets(
    hits: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Convert live Canvas hit geometry to the static PNG viewer contract."""
    targets: list[dict[str, object]] = []
    for hit in hits:
        kind = str(hit.get("kind") or "")
        label = str(hit.get("label") or "")
        legend = str(hit.get("series") or hit.get("legend") or "")
        if kind == "rectangle":
            targets.append({
                "kind": "bar",
                "x": float(hit.get("x") or 0),
                "y": float(hit.get("y") or 0),
                "width": float(hit.get("width") or 0),
                "height": float(hit.get("height") or 0),
                "label": label,
                "legend": legend,
                "value": str(hit.get("value") or ""),
            })
        elif kind == "point":
            x, y = float(hit.get("x") or 0), float(hit.get("y") or 0)
            targets.append({
                "kind": "bar", "x": x - 7, "y": y - 7, "width": 14.0, "height": 14.0,
                "label": label, "legend": legend, "value": str(hit.get("value") or ""),
            })
        elif kind == "line":
            points = hit.get("points") if isinstance(hit.get("points"), list) else []
            if len(points) > MAX_CDF_HOVER_TARGETS_PER_SERIES:
                indexes = sorted({
                    round(index * (len(points) - 1) / (MAX_CDF_HOVER_TARGETS_PER_SERIES - 1))
                    for index in range(MAX_CDF_HOVER_TARGETS_PER_SERIES)
                })
                points = [points[index] for index in indexes]
            series_key = f"{label}\0{legend}"
            for point in points:
                if not isinstance(point, dict):
                    continue
                cumulative = point.get("cumulative")
                targets.append({
                    "kind": "line",
                    "x": float(point.get("x") or 0),
                    "y": float(point.get("y") or 0),
                    "label": label,
                    "legend": legend,
                    "series": series_key,
                    "value": str(point.get("value") or ""),
                    **({"cumulative": f"{float(cumulative) * 100:.1f}%"} if cumulative is not None else {}),
                })
    return targets


def _catalogue_header_key(value: str) -> str:
    """Make harmless spelling/case/separator changes in imported headers equivalent."""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


CATALOG_HEADER_ALIASES = {
    "slide": "Slide",
    "slidetittle": "Slide Tittle",
    "slidetitle": "Slide Tittle",
    "slidesubtittle": "Slide Subtittle",
    "slidesubtitle": "Slide Subtittle",
    "layout": "Layout",
    "charttittle": "Chart Tittle",
    "charttitle": "Chart Tittle",
    "cdrsource": "CDR source",
    "kpi": "KPI",
    "charttype": "Chart type",
    "legend": "Legend",
    "legendposition": "Legend Position",
    "label": "Label",
    "axisxrange": "Axis X Range",
    "axisyrange": "Axis Y Range",
    "excludenullempty": "Exclude Null/Empty",
    "excludezero": "Exclude Zero",
    "filter": "Filters",
    "filters": "Filters",
    "rowsaggregation": "Rows Aggregation",
    "rowaggregation": "Rows Aggregation",
    "groupingrows": "Rows Aggregation",
    "groupingrow": "Rows Aggregation",
    "columnaggregation": "Column Aggregation",
    "columnsaggregation": "Column Aggregation",
    "groupingcolumns": "Column Aggregation",
    "groupingcolumn": "Column Aggregation",
    "grouping": "Grouping",
}


def _canonical_catalog_headers(headers: Iterable[str]) -> tuple[str, ...]:
    """Normalize accepted historic header spellings before schema validation."""
    return tuple(
        CATALOG_HEADER_ALIASES.get(_catalogue_header_key(header), str(header))
        for header in headers
    )


def _default_catalogue_layout(technology: str, chart_count: int) -> str:
    """Choose the standard template layout when a legacy Report Template omitted it."""
    if technology == "nsa":
        return {
            1: "Title and 1 column + Comments",
            2: "Title and 2 columns + Comments",
            3: "Title and 3 columns + Comments",
        }.get(chart_count, "Title and 2 columns and 2 rows + Comments right")
    return {
        1: "Title and 1 column",
        2: "Title and 2 columns",
        3: "Title and 3 columns",
    }.get(chart_count, "Title and 4 columns")


@dataclass(frozen=True)
class FilterCondition:
    column: str
    operator: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class GroupingSpec:
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class CalculatedDimensionRule:
    conditions: tuple[FilterCondition, ...]
    value: str


@dataclass(frozen=True)
class CalculatedDimensionExpressionBranch:
    conditions: tuple[FilterCondition, ...]
    result: str | CalculatedDimensionExpression


@dataclass(frozen=True)
class CalculatedDimensionExpression:
    branches: tuple[CalculatedDimensionExpressionBranch, ...]
    otherwise: str | CalculatedDimensionExpression | None = None


@dataclass(frozen=True)
class CalculatedDimension:
    name: str
    sources: tuple[str, ...]
    rules: tuple[CalculatedDimensionRule, ...]
    default: str = ""
    default_from: tuple[str, ...] = ()
    expression: CalculatedDimensionExpression | None = None
    expression_text: str = ""


def split_calculated_dimension_aliases(value: object) -> tuple[str, ...]:
    """Split alternative source fields from either the legacy pipe or readable OR syntax."""
    aliases: list[str] = []
    for part in re.split(r"\s+(?:OR)\s+|\s*\|\s*", str(value or ""), flags=re.I):
        alias = part.strip()
        if alias.startswith('[') and alias.endswith(']'):
            alias = alias[1:-1].strip()
        if alias:
            aliases.append(alias)
    return tuple(aliases)


@dataclass(frozen=True)
class CatalogEntry:
    slide: int
    slide_title: str
    slide_subtitle: str
    layout: str
    chart_title: str
    cdr_source: str
    kpi: str
    chart_type: str
    legend: str
    filters: str
    grouping_rows: str
    grouping_columns: str
    legend_position: str = "top"
    calculated_dimensions: tuple[CalculatedDimension, ...] = ()
    axis_x_range: str = ""
    axis_y_range: str = ""
    label_position: str = ""
    exclude_null_empty: bool = False
    exclude_zero: bool = False

    @property
    def source_kind(self) -> str | None:
        return CATALOG_SOURCE_KINDS.get(self.cdr_source.strip().casefold())

    @property
    def structural_type(self) -> str | None:
        value = self.chart_type.strip().casefold()
        return value if value in STRUCTURAL_SLIDE_TYPES else None


def parse_catalog_filters(value: str) -> tuple[FilterCondition, ...]:
    """Parse `Column OP value; ...` syntax without needing a particular CDR schema."""
    if not value.strip():
        return ()
    conditions: list[FilterCondition] = []
    # A line break is also accepted as an AND separator because the template
    # editor displays one condition per line. Semicolons remain the canonical
    # persisted separator.
    for clause in (part.strip() for part in re.split(r";|[\r\n]+", value) if part.strip()):
        match = re.fullmatch(r"(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)", clause, flags=re.I)
        if not match:
            raise ValueError(f"Invalid filter '{clause}': expected 'Column OP value' and a semicolon between conditions.")
        column, operator, raw_values = (part.strip() for part in match.groups())
        operator = re.sub(r"\s+", " ", operator).upper()
        # Existing quality-ratio rows describe both output states as "LQ < 1.6 vs ≥ 1.6".
        # That is chart metadata, not a source-row filter.
        if operator in {">", ">=", "<", "<="} and re.search(r"\bvs\b", raw_values, flags=re.I):
            continue
        if not column:
            raise ValueError(f"Invalid filter '{clause}': a column name is required.")
        if operator in {"IN", "NOT IN"}:
            list_match = re.fullmatch(r"\(([^()]*)\)", raw_values)
            if not list_match:
                detail = "a semicolon is required after the closing parenthesis" if re.search(r"\)\s*\S", raw_values) else "IN values must use parentheses"
                raise ValueError(f"Invalid filter '{clause}': {detail}.")
            values = tuple(item.strip() for item in list_match.group(1).split(",") if item.strip())
        elif operator in {"CONTAINS", "NOT CONTAINS"}:
            # A contains condition accepts one term or a comma-separated list.
            # Parentheses are the canonical saved form for lists, but accept a
            # plain list as well so manually authored templates remain clear.
            list_values = raw_values[1:-1] if raw_values.startswith("(") and raw_values.endswith(")") else raw_values
            values = tuple(item.strip() for item in list_values.split(",") if item.strip())
        else:
            values = (raw_values,)
        if not values:
            raise ValueError(f"Invalid filter '{clause}': a value is required.")
        conditions.append(FilterCondition(column, operator, values))
    return tuple(conditions)


@dataclass(frozen=True)
class _CalculatedExpressionToken:
    kind: str
    value: str
    offset: int


def _calculated_expression_tokens(value: str) -> tuple[_CalculatedExpressionToken, ...]:
    tokens: list[_CalculatedExpressionToken] = []
    cursor = 0
    length = len(value)
    while cursor < length:
        whitespace = re.match(r"\s+", value[cursor:])
        if whitespace:
            cursor += len(whitespace.group(0))
            continue
        start = cursor
        character = value[cursor]
        if character == "[":
            end = value.find("]", cursor + 1)
            if end < 0:
                raise ValueError("Invalid IF expression: a source field is missing its closing ']'.")
            tokens.append(_CalculatedExpressionToken("FIELD", value[cursor + 1:end].strip(), start))
            cursor = end + 1
            continue
        if character in {"'", '"'}:
            quote = character
            cursor += 1
            content: list[str] = []
            while cursor < length:
                if value[cursor] == quote:
                    if cursor + 1 < length and value[cursor + 1] == quote:
                        content.append(quote)
                        cursor += 2
                        continue
                    cursor += 1
                    break
                if value[cursor] == "\\" and cursor + 1 < length:
                    content.append(value[cursor + 1])
                    cursor += 2
                    continue
                content.append(value[cursor])
                cursor += 1
            else:
                raise ValueError("Invalid IF expression: a quoted value is not closed.")
            tokens.append(_CalculatedExpressionToken("VALUE", "".join(content), start))
            continue
        operator = re.match(r"<=|>=|!=|<>|=|<|>", value[cursor:])
        if operator:
            tokens.append(_CalculatedExpressionToken("OP", operator.group(0), start))
            cursor += len(operator.group(0))
            continue
        if character in "(),":
            tokens.append(_CalculatedExpressionToken({"(": "LPAREN", ")": "RPAREN", ",": "COMMA"}[character], character, start))
            cursor += 1
            continue
        number = re.match(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value[cursor:])
        if number:
            tokens.append(_CalculatedExpressionToken("VALUE", number.group(0), start))
            cursor += len(number.group(0))
            continue
        word = re.match(r"[A-Za-z_][A-Za-z0-9_.\-/]*", value[cursor:])
        if word:
            tokens.append(_CalculatedExpressionToken("WORD", word.group(0), start))
            cursor += len(word.group(0))
            continue
        raise ValueError(f"Invalid IF expression near character {cursor + 1}: unsupported token '{character}'.")
    return tuple(tokens)


def _strip_calculated_condition_parentheses(
    tokens: tuple[_CalculatedExpressionToken, ...],
) -> tuple[_CalculatedExpressionToken, ...]:
    while len(tokens) >= 2 and tokens[0].kind == "LPAREN" and tokens[-1].kind == "RPAREN":
        depth = 0
        closes_at_end = True
        for index, token in enumerate(tokens):
            if token.kind == "LPAREN":
                depth += 1
            elif token.kind == "RPAREN":
                depth -= 1
                if depth == 0 and index != len(tokens) - 1:
                    closes_at_end = False
                    break
        if not closes_at_end or depth != 0:
            break
        tokens = tokens[1:-1]
    return tokens


def _parse_calculated_expression_condition(
    tokens: tuple[_CalculatedExpressionToken, ...],
) -> FilterCondition:
    tokens = _strip_calculated_condition_parentheses(tokens)
    if len(tokens) < 3 or tokens[0].kind != "FIELD" or not tokens[0].value:
        raise ValueError("Invalid IF condition: use a bracketed source field such as [Mean Data Rate].")
    cursor = 1
    if tokens[cursor].kind == "OP":
        operator = "!=" if tokens[cursor].value == "<>" else tokens[cursor].value
        cursor += 1
    elif tokens[cursor].kind == "WORD":
        operator = tokens[cursor].value.upper()
        cursor += 1
        if operator == "NOT" and cursor < len(tokens) and tokens[cursor].kind == "WORD":
            operator = f"NOT {tokens[cursor].value.upper()}"
            cursor += 1
    else:
        raise ValueError("Invalid IF condition: expected a comparison operator after the source field.")
    if operator not in {"=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "CONTAINS", "NOT CONTAINS"}:
        raise ValueError(f"Invalid IF condition: unsupported operator '{operator}'.")
    remaining = tokens[cursor:]
    if operator in {"IN", "NOT IN"}:
        if len(remaining) < 3 or remaining[0].kind != "LPAREN" or remaining[-1].kind != "RPAREN":
            raise ValueError("Invalid IF condition: IN values must use parentheses.")
        values: list[str] = []
        expect_value = True
        for token in remaining[1:-1]:
            if expect_value and token.kind in {"VALUE", "WORD"}:
                values.append(token.value)
                expect_value = False
            elif not expect_value and token.kind == "COMMA":
                expect_value = True
            else:
                raise ValueError("Invalid IF condition: IN values must be separated by commas.")
        if expect_value or not values:
            raise ValueError("Invalid IF condition: IN requires at least one value.")
        return FilterCondition(tokens[0].value, operator, tuple(values))
    if len(remaining) != 1 or remaining[0].kind not in {"VALUE", "WORD"}:
        raise ValueError("Invalid IF condition: comparisons require one quoted, numeric or single-word value.")
    return FilterCondition(tokens[0].value, operator, (remaining[0].value,))


def _parse_calculated_expression_conditions(
    tokens: tuple[_CalculatedExpressionToken, ...],
) -> tuple[FilterCondition, ...]:
    tokens = _strip_calculated_condition_parentheses(tokens)
    groups: list[tuple[_CalculatedExpressionToken, ...]] = []
    start = 0
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind == "LPAREN":
            depth += 1
        elif token.kind == "RPAREN":
            depth -= 1
        elif depth == 0 and token.kind == "WORD" and token.value.upper() == "AND":
            groups.append(tokens[start:index])
            start = index + 1
    groups.append(tokens[start:])
    if depth != 0 or any(not group for group in groups):
        raise ValueError("Invalid IF condition: unbalanced parentheses or incomplete AND condition.")
    return tuple(_parse_calculated_expression_condition(group) for group in groups)


class _CalculatedExpressionParser:
    def __init__(self, value: str) -> None:
        self.tokens = _calculated_expression_tokens(value)
        self.cursor = 0

    def peek_keyword(self, *values: str) -> bool:
        if self.cursor >= len(self.tokens) or self.tokens[self.cursor].kind != "WORD":
            return False
        return self.tokens[self.cursor].value.upper() in values

    def expect_keyword(self, value: str) -> None:
        if not self.peek_keyword(value):
            found = self.tokens[self.cursor].value if self.cursor < len(self.tokens) else "end of expression"
            raise ValueError(f"Invalid IF expression: expected {value}, found '{found}'.")
        self.cursor += 1

    def condition_before_then(self) -> tuple[FilterCondition, ...]:
        start = self.cursor
        depth = 0
        while self.cursor < len(self.tokens):
            token = self.tokens[self.cursor]
            if token.kind == "LPAREN":
                depth += 1
            elif token.kind == "RPAREN":
                depth -= 1
            elif depth == 0 and token.kind == "WORD" and token.value.upper() == "THEN":
                break
            self.cursor += 1
        if self.cursor >= len(self.tokens):
            raise ValueError("Invalid IF expression: every IF or ELSEIF requires THEN.")
        conditions = _parse_calculated_expression_conditions(self.tokens[start:self.cursor])
        self.cursor += 1
        return conditions

    def result(self) -> str | CalculatedDimensionExpression:
        if self.peek_keyword("IF"):
            return self.expression()
        if self.cursor >= len(self.tokens) or self.tokens[self.cursor].kind not in {"VALUE", "WORD"}:
            raise ValueError("Invalid IF expression: THEN and ELSE require a result value or nested IF block.")
        result = self.tokens[self.cursor].value
        self.cursor += 1
        return result

    def expression(self) -> CalculatedDimensionExpression:
        self.expect_keyword("IF")
        branches = [CalculatedDimensionExpressionBranch(self.condition_before_then(), self.result())]
        while self.peek_keyword("ELSEIF") or (
            self.peek_keyword("ELSE") and self.cursor + 1 < len(self.tokens)
            and self.tokens[self.cursor + 1].kind == "WORD"
            and self.tokens[self.cursor + 1].value.upper() == "IF"
        ):
            if self.peek_keyword("ELSEIF"):
                self.cursor += 1
            else:
                self.cursor += 2
            branches.append(CalculatedDimensionExpressionBranch(self.condition_before_then(), self.result()))
        otherwise: str | CalculatedDimensionExpression | None = None
        if self.peek_keyword("ELSE"):
            self.cursor += 1
            otherwise = self.result()
        self.expect_keyword("END")
        return CalculatedDimensionExpression(tuple(branches), otherwise)

    def parse(self) -> CalculatedDimensionExpression:
        if not self.tokens:
            raise ValueError("IF expression cannot be empty.")
        expression = self.expression()
        if self.cursor != len(self.tokens):
            raise ValueError(f"Invalid IF expression: unexpected token '{self.tokens[self.cursor].value}' after END.")
        return expression


def parse_calculated_dimension_expression(value: str) -> CalculatedDimensionExpression:
    """Parse a Tableau-style IF/THEN/ELSEIF/ELSE/END expression."""
    return _CalculatedExpressionParser(value).parse()


def _flatten_calculated_expression(
    expression: CalculatedDimensionExpression,
    inherited: tuple[FilterCondition, ...] = (),
) -> tuple[CalculatedDimensionRule, ...]:
    rules: list[CalculatedDimensionRule] = []
    for branch in expression.branches:
        conditions = (*inherited, *branch.conditions)
        if isinstance(branch.result, CalculatedDimensionExpression):
            rules.extend(_flatten_calculated_expression(branch.result, conditions))
        else:
            rules.append(CalculatedDimensionRule(conditions, branch.result))
    if expression.otherwise is not None:
        if isinstance(expression.otherwise, CalculatedDimensionExpression):
            rules.extend(_flatten_calculated_expression(expression.otherwise, inherited))
        else:
            rules.append(CalculatedDimensionRule(inherited, expression.otherwise))
    return tuple(rules)


def parse_calculated_dimensions(payload: object) -> tuple[CalculatedDimension, ...]:
    """Validate workspace-owned auto-calculated fields from their JSON representation."""
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ValueError("Auto-calculated fields must be a list.")
    dimensions: list[CalculatedDimension] = []
    names: set[str] = set()
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Auto-calculated field {index} must be an object.")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"Auto-calculated field {index} requires a name.")
        identity = _normalise_catalog_name(name)
        if not identity or identity in names:
            raise ValueError(f"Auto-calculated field name '{name}' is duplicated or invalid.")
        names.add(identity)
        raw_sources = item.get("sources")
        if raw_sources is None:
            raw_sources = list(CATALOG_SOURCE_KINDS)
        if not isinstance(raw_sources, list):
            raise ValueError(f"Auto-calculated field '{name}' must define its CDR sources as a list.")
        sources = tuple(dict.fromkeys(str(value).strip().casefold() for value in raw_sources if str(value).strip()))
        if not sources or any(source not in CATALOG_SOURCE_KINDS for source in sources):
            raise ValueError(f"Auto-calculated field '{name}' contains an unsupported CDR source.")
        expression_text = str(item.get("expression") or "").strip()
        expression = parse_calculated_dimension_expression(expression_text) if expression_text else None
        raw_rules = item.get("rules") or []
        if not isinstance(raw_rules, list):
            raise ValueError(f"Auto-calculated field '{name}' rules must be a list.")
        rules: list[CalculatedDimensionRule] = []
        for rule_index, rule in enumerate(raw_rules, start=1):
            if not isinstance(rule, Mapping):
                raise ValueError(f"Rule {rule_index} of auto-calculated field '{name}' must be an object.")
            when = str(rule.get("when") or "").strip()
            value = str(rule.get("value") or "").strip()
            if not when or not value:
                raise ValueError(f"Rule {rule_index} of auto-calculated field '{name}' requires a condition and result.")
            rules.append(CalculatedDimensionRule(parse_catalog_filters(when), value))
        if expression is not None:
            rules = list(_flatten_calculated_expression(expression))
        default_from = split_calculated_dimension_aliases(item.get("default_from"))
        default = str(item.get("default") or "")
        if not rules and not default_from and not default:
            raise ValueError(f"Auto-calculated field '{name}' requires at least one rule, a default value or a default source field.")
        dimensions.append(CalculatedDimension(
            name, sources, tuple(rules), default, default_from, expression, expression_text,
        ))
    return tuple(dimensions)


def calculated_dimensions_json(dimensions: Iterable[CalculatedDimension]) -> list[dict[str, object]]:
    """Return the stable, editable JSON representation for template metadata."""
    def compact_column_aliases(value: str) -> str:
        """Keep distinct physical fallbacks while removing case-only duplicates."""
        aliases: list[str] = []
        seen: set[str] = set()
        for candidate in split_calculated_dimension_aliases(value):
            key = _normalise_catalog_name(candidate)
            if candidate and key not in seen:
                aliases.append(candidate)
                seen.add(key)
        return " OR ".join(f"[{alias}]" for alias in aliases)

    def condition_text(condition: FilterCondition) -> str:
        values = ", ".join(condition.values)
        value = f"({values})" if condition.operator in {"IN", "NOT IN"} or len(condition.values) > 1 else values
        return f"{compact_column_aliases(condition.column)} {condition.operator} {value}"

    return [
        {
            "name": dimension.name,
            "sources": list(dimension.sources),
            "default": dimension.default,
            "default_from": compact_column_aliases("|".join(dimension.default_from)),
            "expression": dimension.expression_text,
            "rules": [
                {"when": "; ".join(condition_text(condition) for condition in rule.conditions), "value": rule.value}
                for rule in dimension.rules
            ],
        }
        for dimension in dimensions
    ]


def parse_catalog_grouping(value: str) -> GroupingSpec:
    if not value.strip():
        return GroupingSpec(())
    dimensions = tuple(part.strip() for part in re.split(r"\s*×\s*|\s+\bx\b\s+", value, flags=re.I) if part.strip())
    if not dimensions:
        raise ValueError("Grouping must contain at least one dimension.")
    return GroupingSpec(dimensions)


def parse_legend_position(value: str) -> str:
    """Return the canonical legend position declared by a Report Template row."""
    normalized = value.strip().casefold()
    if not normalized:
        return "top"
    aliases = {
        "top": "top", "above": "top", "arriba": "top",
        "bottom": "bottom", "below": "bottom", "abajo": "bottom",
        "left": "left", "izquierda": "left",
        "right": "right", "derecha": "right",
    }
    if normalized not in aliases:
        raise ValueError("Legend Position must be Top, Bottom, Left or Right.")
    return aliases[normalized]


def parse_label_position(value: str) -> str:
    """Return the canonical bar-label placement declared by a template row."""
    normalized = value.strip().casefold()
    if not normalized:
        return ""
    if normalized not in {"none", "top", "up", "middle", "down"}:
        raise ValueError("Label must be None, Top, Up, Middle or Down.")
    return normalized


def parse_template_boolean(value: object, field: str) -> bool:
    """Parse an optional Yes/No template switch."""
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if not normalized or normalized in {"no", "false", "0"}:
        return False
    if normalized in {"yes", "true", "1"}:
        return True
    raise ValueError(f"{field} must be Yes, No or empty.")


def parse_axis_range(value: str, axis: str) -> tuple[float | None, float | None]:
    """Parse a template axis range such as ``[0.01,]`` or ``[,30]``."""
    raw = value.strip()
    if not raw:
        return None, None
    match = re.fullmatch(r"\[\s*([^,\]]*)\s*,\s*([^\]]*)\s*\]", raw)
    if not match:
        raise ValueError(f"Axis {axis.upper()} Range must use [min,max], [min,] or [,max].")
    values: list[float | None] = []
    for part in match.groups():
        if not part.strip():
            values.append(None)
            continue
        try:
            number = float(part)
        except ValueError as exc:
            raise ValueError(f"Axis {axis.upper()} Range limits must be numbers.") from exc
        if not math.isfinite(number):
            raise ValueError(f"Axis {axis.upper()} Range limits must be finite numbers.")
        values.append(number)
    low, high = values
    if low is None and high is None:
        raise ValueError(f"Axis {axis.upper()} Range must define at least one limit.")
    if low is not None and high is not None and low >= high:
        raise ValueError(f"Axis {axis.upper()} Range minimum must be lower than its maximum.")
    return low, high


def parse_catalog_csv(content: bytes | str, technology: str, *, validate_filters: bool = True) -> list[CatalogEntry]:
    """Validate the editable report-template CSV and return its chart rows."""
    if technology not in TEMPLATE_NAMES:
        raise ValueError("Catalog technology must be NSA or SA.")
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The report template must be a UTF-8 CSV file.") from exc
    else:
        text = content
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = tuple(reader.fieldnames or ())
    accepted_schemas = {
        _canonical_catalog_headers(schema)
        for schema in (CATALOG_HEADERS, VISUAL_CATALOG_HEADERS, RANGELESS_CATALOG_HEADERS, PREVIOUS_CATALOG_HEADERS, OLDER_CATALOG_HEADERS, LEGACY_ROWS_COLUMNS_HEADERS, LEGACY_CATALOG_HEADERS)
    }
    if _canonical_catalog_headers(fieldnames) not in accepted_schemas:
        raise ValueError("The report template must use exactly these columns: " + ", ".join(CATALOG_HEADERS))
    entries: list[CatalogEntry] = []
    chart_positions: defaultdict[int, int] = defaultdict(int)
    for line_number, row in enumerate(reader, start=2):
        row = {
            CATALOG_HEADER_ALIASES.get(_catalogue_header_key(key), key): value
            for key, value in row.items()
        }
        try:
            slide = int((row.get("Slide") or "").strip())
        except ValueError as exc:
            raise ValueError(f"Catalog row {line_number} has an invalid Slide value.") from exc
        if slide < 1:
            raise ValueError(f"Catalog row {line_number} must use a positive slide number.")
        legacy_grouping = (row.get("Grouping") or "").strip()
        legacy_dimensions = parse_catalog_grouping(legacy_grouping).dimensions
        entry = CatalogEntry(
            slide=slide,
            slide_title=(row.get("Slide Tittle") or "").strip().replace("\\n", "\n"),
            slide_subtitle=(row.get("Slide Subtittle") or "").strip().replace("\\n", "\n"),
            layout=(row.get("Layout") or "").strip(),
            chart_title=(row.get("Chart Tittle") or "").strip().replace("\\n", "\n"),
            cdr_source=(row.get("CDR source") or "").strip(),
            kpi=(row.get("KPI") or "").strip(),
            chart_type=(row.get("Chart type") or "").strip(),
            legend=(row.get("Legend") or "").strip(),
            # Keep an intentionally empty editor cell empty. Renderers still
            # interpret it as their default position if a legend exists.
            legend_position=(row.get("Legend Position") or "").strip().casefold(),
            filters=(row.get("Filters") or "").strip(),
            grouping_rows=((row.get("Rows Aggregation") or row.get("Grouping_Rows") or "").strip() or " × ".join(legacy_dimensions[:1])),
            grouping_columns=((row.get("Column Aggregation") or row.get("Grouping_Columns") or "").strip() or " × ".join(legacy_dimensions[1:])),
            axis_x_range=(row.get("Axis X Range") or "").strip(),
            axis_y_range=(row.get("Axis Y Range") or "").strip(),
            label_position=parse_label_position(row.get("Label") or ""),
            exclude_null_empty=parse_template_boolean(row.get("Exclude Null/Empty") or "", "Exclude Null/Empty"),
            exclude_zero=parse_template_boolean(row.get("Exclude Zero") or "", "Exclude Zero"),
        )
        if entry.source_kind:
            chart_positions[entry.slide] += 1
        editor_location = f"Slide: {entry.slide} - Chart: {chart_positions[entry.slide]}" if entry.source_kind else f"Slide: {entry.slide}"
        if entry.structural_type:
            if not entry.slide_title:
                raise ValueError(f"Catalog row {line_number} requires Slide Tittle for a structural slide.")
            if not entry.layout:
                raise ValueError(f"Catalog row {line_number} requires Layout for a structural slide.")
            structural_chart_fields = (
                entry.chart_title, entry.cdr_source, entry.kpi, entry.legend,
                entry.filters, entry.grouping_rows, entry.grouping_columns,
                entry.axis_x_range, entry.axis_y_range, entry.label_position,
            )
            if any(value.strip() for value in structural_chart_fields) or entry.exclude_null_empty or entry.exclude_zero:
                raise ValueError(
                    f"Catalog row {line_number} is a {entry.chart_type} and cannot define chart, CDR, KPI, "
                    "legend, filter or grouping values."
                )
        if entry.source_kind and not entry.slide_title:
            raise ValueError(f"Catalog row {line_number} requires Slide Tittle for a CDR source.")
        if entry.source_kind and not entry.layout:
            raise ValueError(f"Catalog row {line_number} requires Layout for a CDR source.")
        if entry.cdr_source and entry.cdr_source.casefold() not in CATALOG_SOURCE_KINDS:
            raise ValueError(f"Catalog row {line_number} has unsupported CDR source '{entry.cdr_source}'.")
        if not entry.source_kind and not entry.structural_type and entry.chart_type.casefold() not in PRESERVED_CHART_TYPES:
            raise ValueError(
                f"Catalog row {line_number} must define a supported CDR chart, Title Slide or Transition Slide."
            )
        if entry.source_kind and (not entry.kpi or not entry.chart_type):
            raise ValueError(f"Catalog row {line_number} requires KPI and Chart type for a CDR source.")
        if entry.source_kind and entry.chart_type.casefold() not in CHART_TYPES:
            raise ValueError(f"Catalog row {line_number} has unsupported Chart type '{entry.chart_type}'.")
        if entry.source_kind and not (entry.grouping_rows or entry.grouping_columns):
            raise ValueError(f"Catalog row {line_number} requires Rows Aggregation or Column Aggregation for a CDR source.")
        try:
            if validate_filters:
                parse_catalog_filters(entry.filters)
            parse_catalog_grouping(entry.grouping_rows)
            parse_catalog_grouping(entry.grouping_columns)
            parse_legend_position(entry.legend_position)
            parse_label_position(entry.label_position)
            parse_axis_range(entry.axis_x_range, "x")
            parse_axis_range(entry.axis_y_range, "y")
        except ValueError as exc:
            raise ValueError(f"{editor_location} -> {exc}") from exc
        entries.append(entry)
    if not entries:
        raise ValueError("The report template does not contain any rows.")
    entries_by_slide: dict[int, list[CatalogEntry]] = defaultdict(list)
    for entry in entries:
        entries_by_slide[entry.slide].append(entry)
    for slide_number, slide_entries in entries_by_slide.items():
        structural_entries = [entry for entry in slide_entries if entry.structural_type]
        if structural_entries and len(slide_entries) != 1:
            raise ValueError(
                f"Slide {slide_number} cannot combine a structural Title/Transition row with chart rows."
            )
    return entries


def convert_catalog_csv(content: bytes | str, technology: str) -> bytes:
    """Migrate a compatible legacy CSV into the current editable Report Templates schema.

    The importer deliberately accepts common title spelling variants and the former
    single ``Grouping`` column.  Missing newer presentation-only columns are left
    blank, while the normal validator still protects required report definitions.
    """
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The report template must be a UTF-8 CSV file.") from exc
    else:
        text = content
    reader = csv.DictReader(io.StringIO(text))
    original_headers = tuple(reader.fieldnames or ())
    if not original_headers:
        raise ValueError("The report template does not contain a header row.")

    header_map: dict[str, str] = {}
    for original in original_headers:
        canonical = CATALOG_HEADER_ALIASES.get(_catalogue_header_key(original))
        if canonical and canonical not in header_map:
            header_map[canonical] = original
    if "Slide" not in header_map:
        raise ValueError("The uploaded CSV cannot be converted because it does not contain a Slide column.")

    converted_rows: list[dict[str, str]] = []
    for row in reader:
        converted = {header: "" for header in CATALOG_HEADERS}
        for canonical, original in header_map.items():
            if canonical == "Grouping":
                continue
            converted[canonical] = (row.get(original) or "").strip()
        legacy_grouping = (row.get(header_map.get("Grouping", "")) or "").strip()
        if legacy_grouping:
            dimensions = parse_catalog_grouping(legacy_grouping).dimensions
            if not converted["Rows Aggregation"]:
                converted["Rows Aggregation"] = " × ".join(dimensions[:1])
            if not converted["Column Aggregation"]:
                converted["Column Aggregation"] = " × ".join(dimensions[1:])
        converted_rows.append(converted)

    # Older templates did not contain a Layout column. Its suitable default is
    # determined by the number of automated charts represented by that slide.
    charts_per_slide: dict[str, int] = defaultdict(int)
    for row in converted_rows:
        if row["CDR source"].strip().casefold() in CATALOG_SOURCE_KINDS:
            charts_per_slide[row["Slide"].strip()] += 1
    for row in converted_rows:
        if (
            not row["Layout"].strip()
            and row["CDR source"].strip().casefold() in CATALOG_SOURCE_KINDS
        ):
            row["Layout"] = _default_catalogue_layout(technology, charts_per_slide[row["Slide"].strip()])

    # A slide-less template cannot preserve source slides. Migrate the former
    # preservation marker into an explicit structural slide contract instead.
    for row in converted_rows:
        if row["Chart type"].strip().casefold() not in PRESERVED_CHART_TYPES:
            continue
        is_title = row["Slide"].strip() == "1"
        row["Chart type"] = "Title Slide" if is_title else "Transition Slide"
        row["Layout"] = row["Layout"].strip() or ("Title Page" if is_title else "Title Only")

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CATALOG_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(converted_rows)
    converted_content = output.getvalue().encode("utf-8")
    # Reuse the regular validator so a conversion never imports an incomplete chart
    # contract just because it used an older set of column headings.
    entries = parse_catalog_csv(converted_content, technology)
    return catalogue_csv(entries)


def load_catalog_csv(path: Path, technology: str, *, validate_filters: bool = True) -> list[CatalogEntry]:
    return parse_catalog_csv(path.read_bytes(), technology, validate_filters=validate_filters)


def active_catalog_path(catalog_dir: Path, fallback_catalog: Path, technology: str) -> Path:
    """Return the built-in Report Template kept in the technology library."""
    return fallback_catalog


def catalogue_csv(entries: list[CatalogEntry]) -> bytes:
    """Serialize the active template using the current editable CSV schema."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CATALOG_HEADERS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow({
            "Slide": entry.slide,
            "Slide Tittle": entry.slide_title.replace("\n", "\\n"),
            "Slide Subtittle": entry.slide_subtitle.replace("\n", "\\n"),
            "Layout": entry.layout,
            "Chart Tittle": entry.chart_title.replace("\n", "\\n"),
            "CDR source": entry.cdr_source,
            "KPI": entry.kpi,
            "Chart type": entry.chart_type,
            "Filters": entry.filters,
            "Rows Aggregation": entry.grouping_rows,
            "Column Aggregation": entry.grouping_columns,
            "Legend": entry.legend,
            "Legend Position": entry.legend_position.title(),
            "Label": entry.label_position.title(),
            "Axis X Range": entry.axis_x_range,
            "Axis Y Range": entry.axis_y_range,
            "Exclude Null/Empty": "Yes" if entry.exclude_null_empty else "",
            "Exclude Zero": "Yes" if entry.exclude_zero else "",
        })
    return output.getvalue().encode("utf-8")


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

NEUTRAL_SERIES_COLORS = ("#6F42C1", "#2E8B57", "#A0612A", "#C23B8B", "#607D8B", "#B8860B")

# Tableau palette used by the throughput-below calculation, ordered from the
# lowest bucket through the successful Above bucket.
THROUGHPUT_DISTRIBUTION_COLORS = ("#FF9DA7", "#F28E2B", "#E15759", "#76B7B2", "#4E79A7")

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
    """Return the operator form used by the Vendor-mapping business formula."""
    text = str(value or "").strip()
    key = re.sub(r"[^a-z0-9]+", "", text.casefold())
    if key in {"3", "3uk", "three", "threeuk"}:
        return "3"
    if key in {"vodafone", "vodafoneuk", "vf", "vfuk"}:
        return "Vodafone UK"
    return text


def _normalise_operator_label(value: object, mappings: dict[str, str] | None = None) -> str:
    """Return an Admin-configured label, or preserve the supplied label."""
    text = str(value or "").strip()
    configured = mappings or {}
    return configured.get(text.casefold(), text)


def _operator_sort_label(value: object) -> str:
    """Return the displayed operator identity; ordering comes from Admin."""
    return str(value or '').strip()


def _split_operator_vendor(
    value: object,
    operator_mappings: dict[str, str] | None = None,
    vendor_mappings: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Split a combined identity without truncating operators containing underscores."""
    text = str(value or '').strip()
    candidates = [
        (text[:index], '_', text[index + 1:])
        for index, character in enumerate(text)
        if character == '_' and text[:index].strip() and text[index + 1:].strip()
    ]
    if not candidates:
        return text, '', ''
    operators = {str(key).strip().casefold() for key in (operator_mappings or {})}
    vendors = {str(key).strip().casefold() for key in (vendor_mappings or {})}
    # A complete configured Operator is never an Operator_Vendor composite.
    # Resolve this before inspecting underscores so VF_SA cannot become
    # Operator VF plus Vendor SA, even when both VF and SA are configured.
    if text.casefold() in operators:
        return text, '', ''
    recognised = [
        candidate for candidate in candidates
        if candidate[0].strip().casefold() in operators or candidate[2].strip().casefold() in vendors
    ]
    if recognised:
        return max(recognised, key=lambda candidate: (
            candidate[0].strip().casefold() in operators,
            candidate[2].strip().casefold() in vendors,
            len(candidate[0]),
        ))
    return candidates[0]


def _vendor_operator(value: object, mappings: dict[str, str] | None = None) -> str:
    """Return the operator prefix from an ``Operator_Vendor`` value."""
    operator, _separator, _vendor = _split_operator_vendor(value, mappings)
    return _normalise_operator_label(operator, mappings)


def _normalise_vendor(
    value: object,
    operator_mappings: dict[str, str] | None = None,
    vendor_mappings: dict[str, str] | None = None,
) -> str:
    """Normalise both halves of an ``Operator_Vendor`` label from Admin data."""
    text = str(value or "").strip()
    operator, separator, vendor = _split_operator_vendor(text, operator_mappings, vendor_mappings)
    if separator:
        normalized_operator = _normalise_operator_label(operator, operator_mappings)
        normalized_vendor = _normalise_operator_label(vendor, vendor_mappings)
        return f"{normalized_operator}_{normalized_vendor}"
    vendor_label = _normalise_operator_label(text, vendor_mappings)
    return vendor_label if vendor_label != text else _normalise_operator_label(text, operator_mappings)


def normalise_operator_aliases(frame: pd.DataFrame, mappings: dict[str, str] | None = None) -> pd.DataFrame:
    """Apply only the operator aliases explicitly configured in Admin.

    No default aliases exist. Without workspace mappings, both ``Operator``
    and the operator prefix of ``Vendor`` retain the exact CDR label.
    """
    result = frame.copy()
    source_mappings = mappings if mappings is not None else frame.attrs.get('operator_mappings', {})
    configured = {str(key).strip().casefold(): str(value).strip() for key, value in source_mappings.items()}
    vendor_mappings = {
        str(key).strip().casefold(): str(value).strip()
        for key, value in frame.attrs.get('vendor_mappings', {}).items()
    }
    def mapped(value: object) -> object:
        if pd.isna(value) or not str(value).strip():
            return value
        return _normalise_operator_label(value, configured)
    for column in result.columns:
        if _normalise_catalog_name(str(column)) == "operator":
            result[column] = result[column].map(mapped)
    for vendor_column in [
        column for column in result.columns
        if _normalise_catalog_name(str(column)) in {"vendor", "vendoronly", "operatorvendor"}
    ]:
        def mapped_vendor(value: object) -> object:
            if pd.isna(value) or not str(value).strip():
                return value
            return _normalise_vendor(value, configured, vendor_mappings)
        result[vendor_column] = result[vendor_column].map(mapped_vendor)
    result.attrs['operator_aliases_normalized'] = True
    result.attrs['operator_mappings'] = configured
    result.attrs['vendor_mappings'] = vendor_mappings
    return result


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
    # NetCheck exports are not entirely consistent between releases: a field can
    # be written as ``Cell_ID_A``, ``CELL ID A`` or ``cell-id-a``.  Treat only
    # spelling separators and case as insignificant, while retaining the
    # original column name for the caller.
    for candidate in candidates:
        actual = resolve_column_name(df.columns, candidate)
        if actual:
            return actual
    return None


def classify_sessions(df: pd.DataFrame, technology: str) -> pd.DataFrame:
    main_rat_column = _first_existing(df, ["RAT", "RAT_A"])
    sample_rat_column = _first_existing(df, ["Sample_RAT_A"])
    normalized_rat_column = _first_existing(df, ["technology_primary"])
    rat_column = main_rat_column or sample_rat_column or normalized_rat_column
    call_mode_columns = list(dict.fromkeys(filter(None, (
        _first_existing(df, ["L1_Call_Mode_A", "L1_call_Mode_A"]),
        _first_existing(df, ["L2_Call_Mode_A", "L2_call_Mode_A"]),
    ))))
    if not rat_column and not call_mode_columns:
        raise ValueError("The selected CDR does not contain RAT or Call Mode fields required to separate NSA and SA sessions.")

    # WhatsApp's explicit RAT describes the packet session and remains
    # authoritative. Native and MultiRAB calls are classified by their call
    # mode first: a plain LTE RAT is common for valid VoLTE calls and must not
    # make those samples disappear from an NSA report.
    rat_values = (
        df[rat_column].fillna("").astype(str).str.strip()
        if rat_column else pd.Series("", index=df.index, dtype="string")
    )
    call_modes = pd.Series("", index=df.index, dtype="string")
    for column in call_mode_columns:
        call_modes = call_modes.str.cat(df[column].fillna("").astype(str), sep=" ")
    session_column = _first_existing(df, ["Session_Type", "session_type"])
    session_values = (
        df[session_column].fillna("").astype(str)
        if session_column else pd.Series("", index=df.index, dtype="string")
    )
    whatsapp = session_values.str.contains("whatsapp", case=False, na=False)
    recognised_call_mode = call_modes.str.contains(r"VoLTE|EPSFB|VoNR", case=False, na=False, regex=True)

    rat_nsa = rat_values.str.contains(r"EN[- ]?DC", case=False, na=False, regex=True)
    rat_sa = rat_values.str.contains(r"NR", case=False, na=False, regex=True) & ~rat_nsa
    mode_nsa = call_modes.str.contains(r"VoLTE|EPSFB", case=False, na=False, regex=True)
    mode_sa = call_modes.str.contains(r"VoNR", case=False, na=False, regex=True)
    conflicting_call_mode = mode_nsa & mode_sa
    mode_nsa &= ~conflicting_call_mode
    mode_sa &= ~conflicting_call_mode
    multirab_lte_fallback = (
        session_values.str.contains("multirab", case=False, na=False)
        & rat_values.str.contains(r"(?:^|/)LTE(?:/|$)", case=False, na=False, regex=True)
    )

    if technology == "nsa":
        mask = (whatsapp & rat_nsa) | (~whatsapp & (mode_nsa | (~recognised_call_mode & (rat_nsa | multirab_lte_fallback))))
    else:
        mask = (whatsapp & rat_sa) | (~whatsapp & (mode_sa | (~recognised_call_mode & rat_sa)))
    return df[mask].copy()


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
    cell_column = _first_existing(result, [
        "Cell_ID_A", "Cell_IDs_A", "Cell_ID", "Cell ID A", "Cell IDs A",
        "Global_Cell_ID_A", "Global_Cell_ID", "Global CI", "Global_CI",
        "GCID", "GCI", "CGI", "ECI", "Serving_Cell_ID",
    ])
    if not operator_column or not cell_column:
        raise ValueError("The selected CDR must contain Operator and a supported Cell ID field for multivendor reporting.")
    vodafone_lookup = build_vodafone_vendor_lookup(vodafone_mapping)
    three_lookup = build_three_vendor_lookup(three_mapping)
    result["vendor"] = [
        vendor_from_cells(
            operator,
            cells,
            vodafone_lookup if _normalise_operator(operator) == "Vodafone UK" else three_lookup,
        )
        for operator, cells in result[[operator_column, cell_column]].itertuples(index=False)
    ]
    return result


def assign_cdr_vendors(
    df: pd.DataFrame,
    vodafone_mapping: pd.DataFrame | None = None,
    three_mapping: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Assign the agreed multivendor value to the normalized CDR ``vendor`` field.

    This is the persistent Workspace counterpart of report-time enrichment.  The
    same first/last ``Cell_ID_A`` and operator formula is used, while allowing a
    CDR to be mapped with the VFUK and/or 3UK mapping files available in its
    Workspace.
    """
    result = df.copy()
    # A source Vendor is replaced by the calculated multivendor result. Keep
    # one canonical field instead of persisting parallel source/derived names.
    vendor_collision_columns = [
        str(column) for column in result.columns
        if column_identity(column) in {'vendor', 'reportvendor'} or re.fullmatch(r'vendor__\d+', str(column).casefold())
    ]
    if vendor_collision_columns:
        result = result.drop(columns=vendor_collision_columns)
    operator_column = _first_existing(result, ["operator", "Operator"])
    cell_column = _first_existing(result, [
        "Cell_ID_A", "Cell_IDs_A", "Cell_ID", "Cell ID A", "Cell IDs A",
        "Global_Cell_ID_A", "Global_Cell_ID", "Global CI", "Global_CI",
        "GCID", "GCI", "CGI", "ECI", "Serving_Cell_ID",
    ])
    if not operator_column or not cell_column:
        raise ValueError(
            "The selected CDR must contain Operator and a Cell ID field. "
            "Supported names include Cell_ID_A, Cell_IDs_A, Cell_ID, Global CI, GCID, GCI, CGI or ECI."
        )

    vodafone_lookup = build_vodafone_vendor_lookup(vodafone_mapping) if vodafone_mapping is not None else {}
    three_lookup = build_three_vendor_lookup(three_mapping) if three_mapping is not None else {}
    assigned_vendors: list[object] = []
    for operator, cells in result[[operator_column, cell_column]].itertuples(index=False):
        normalized_operator = _normalise_operator(operator)
        if normalized_operator == "Vodafone UK":
            if vodafone_mapping is None:
                assigned_vendors.append(normalized_operator)
            else:
                mapped_value = vendor_from_cells(operator, cells, vodafone_lookup)
                assigned_vendors.append(mapped_value)
        elif normalized_operator == "3":
            if three_mapping is None:
                assigned_vendors.append(normalized_operator)
            else:
                mapped_value = vendor_from_cells(operator, cells, three_lookup)
                assigned_vendors.append(mapped_value)
        else:
            # Operators without a multivendor mapping use their canonical
            # Operator value as the official Vendor comparison identity.
            assigned_vendors.append(normalized_operator)
    result["vendor"] = assigned_vendors
    vendor_only_column = resolve_column_name(result.columns, 'Vendor_Only') or 'Vendor_Only'
    operator_values = result[operator_column].fillna('').astype(str).str.strip()
    vendor_values = result['vendor'].fillna('').astype(str).str.strip()
    result[vendor_only_column] = [
        vendor_only_value(value, operator)
        for value, operator in zip(vendor_values, operator_values, strict=False)
    ]
    # Keep the calculated Vendor immediately after the source-sheet identifier
    # (or first when no worksheet identifier exists).
    leading_columns = [column for column in ('source_sheet', 'vendor') if column in result.columns]
    remaining_columns = [column for column in result.columns if column not in set(leading_columns)]
    return result.loc[:, [*leading_columns, *remaining_columns]]


def ensure_vendor_group(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the official Vendor field contains every comparison identity."""
    result = df.copy()
    operator_column = _first_existing(result, ["operator", "Operator"])
    vendor_column = _first_existing(result, ["vendor", "Vendor"])
    if not operator_column:
        return result
    operators = result[operator_column].fillna("").astype(str).str.strip()
    if vendor_column:
        vendors = result[vendor_column].fillna("").astype(str).str.strip()
        result[vendor_column] = vendors.where(vendors.ne(""), operators)
    else:
        result["Vendor"] = operators
    legacy_column = _first_existing(result, ["report_vendor"])
    if legacy_column:
        result = result.drop(columns=[legacy_column])
    return result


def _replace_word(value: str, source: str, replacement: str) -> str:
    """Replace a template word while retaining the source word's casing."""
    def replace_match(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.isupper():
            return replacement.upper()
        if word[0].isupper():
            return replacement.capitalize()
        return replacement.lower()
    return re.sub(rf"\b{re.escape(source)}\b", replace_match, value, flags=re.I)


def _replace_operator_label(value: str, replacement: str) -> str:
    """Replace singular and plural display labels without touching filters."""
    return _replace_word(_replace_word(value, "Operators", f"{replacement}s"), "Operator", replacement)


def prepare_multivendor_catalog_entry(entry: CatalogEntry) -> CatalogEntry:
    """Apply the report-only multivendor wording and grouping interpretation.

    The stored template remains an operator-oriented definition.  For a
    multivendor run, grouping dimensions, display legends and titles are
    transformed and unresolved Mixed/Other vendor groups are excluded. Existing
    ``Operator`` conditions remain untouched.  During filtering they resolve
    against the operator prefix of the materialised ``Operator_Vendor`` value.
    """
    def vendor_grouping(value: str) -> str:
        """Expand comparison identities into Vendor then Operator levels."""
        dimensions = parse_catalog_grouping(value).dimensions
        expanded: list[str] = []
        for dimension in dimensions:
            normalized = _normalise_catalog_name(dimension)
            if normalized in {"operator", "vendor"}:
                if not any(_normalise_catalog_name(item) == "vendor" for item in expanded):
                    expanded.append("Vendor")
                if not any(_normalise_catalog_name(item) == "operator" for item in expanded):
                    expanded.append("Operator")
            else:
                expanded.append(dimension)
        return " × ".join(expanded)

    def vendor_legend(value: str) -> str:
        """Keep multivendor legend dimensions in Vendor/Operator hierarchy."""
        if not value or _legend_labels(value):
            return value
        dimensions = _legend_dimensions(value)
        if not any(_normalise_catalog_name(item) in {"operator", "vendor"} for item in dimensions):
            return value
        expanded: list[str] = []
        for dimension in dimensions:
            if _normalise_catalog_name(dimension) in {"operator", "vendor"}:
                if "Vendor" not in expanded:
                    expanded.extend(("Vendor", "Operator"))
            else:
                expanded.append(dimension)
        return ", ".join(expanded)

    filters = entry.filters.strip()
    vendor_exclusion = "vendor NOT CONTAINS (Mixed, Other)"
    has_vendor_exclusion = any(
        _normalise_catalog_name(condition.column) == "vendor"
        and condition.operator == "NOT CONTAINS"
        and {value.casefold() for value in condition.values}.issuperset({"mixed", "other"})
        for condition in parse_catalog_filters(filters)
    )
    if entry.source_kind and not has_vendor_exclusion:
        filters = f"{filters.rstrip(';')}; {vendor_exclusion}" if filters else vendor_exclusion

    return replace(
        entry,
        slide_title=_replace_operator_label(entry.slide_title, "Vendor"),
        slide_subtitle=_replace_operator_label(entry.slide_subtitle, "Vendor"),
        chart_title=_replace_operator_label(entry.chart_title, "Vendor"),
        # Keep both levels in Vendor-first comparison legends so the same
        # vendor used by two operators remains distinguishable.
        legend=vendor_legend(entry.legend),
        grouping_rows=vendor_grouping(entry.grouping_rows),
        grouping_columns=vendor_grouping(entry.grouping_columns),
        filters=filters,
    )


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    return load_image_font(size, bold)


def _column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    return _first_existing(frame, candidates)


def _period_column(frame: pd.DataFrame) -> str | None:
    return _column(frame, ("Campaign", "period", "Period", "Quarter"))


def _group_column(frame: pd.DataFrame, multivendor: bool) -> str | None:
    return _column(frame, ("Vendor", "vendor")) if multivendor else _column(frame, ("Operator", "operator"))


def _normalise_catalog_name(value: str) -> str:
    return column_identity(value)


def _calculated_condition_mask(frame: pd.DataFrame, condition: FilterCondition) -> pd.Series | None:
    column = _column(frame, split_calculated_dimension_aliases(condition.column))
    if not column:
        return None
    series = frame[column]
    if condition.operator in {">", ">=", "<", "<=", "=", "!="}:
        target = condition.values[0]
        numeric = pd.to_numeric(series, errors="coerce")
        target_number = pd.to_numeric(pd.Series([target]), errors="coerce").iloc[0]
        if pd.notna(target_number):
            return {">": numeric > target_number, ">=": numeric >= target_number, "<": numeric < target_number,
                    "<=": numeric <= target_number, "=": numeric == target_number, "!=": numeric != target_number}[condition.operator]
        text = series.astype("string").str.casefold()
        return text.eq(target.casefold()) if condition.operator == "=" else text.ne(target.casefold()) if condition.operator == "!=" else None
    if condition.operator in {"CONTAINS", "NOT CONTAINS"}:
        mask = pd.Series(False, index=frame.index)
        text = series.astype("string")
        for target in condition.values:
            mask |= text.str.contains(target, case=False, na=False, regex=False)
        return ~mask if condition.operator == "NOT CONTAINS" else mask
    accepted = {value.casefold() for value in condition.values}
    mask = series.astype("string").str.casefold().isin(accepted)
    return ~mask if condition.operator == "NOT IN" else mask


def _calculated_conditions_mask(
    frame: pd.DataFrame, conditions: Iterable[FilterCondition],
) -> pd.Series | None:
    mask = pd.Series(True, index=frame.index)
    for condition in conditions:
        condition_mask = _calculated_condition_mask(frame, condition)
        if condition_mask is None:
            return None
        mask &= condition_mask.fillna(False)
    return mask


def _calculated_expression_values(
    frame: pd.DataFrame, expression: CalculatedDimensionExpression,
) -> pd.Series:
    output = pd.Series(pd.NA, index=frame.index, dtype="string")
    remaining = pd.Series(True, index=frame.index)
    for branch in expression.branches:
        mask = _calculated_conditions_mask(frame, branch.conditions)
        if mask is None:
            continue
        selected = remaining & mask
        if isinstance(branch.result, CalculatedDimensionExpression):
            nested = _calculated_expression_values(frame, branch.result)
            output.loc[selected] = nested.loc[selected]
        else:
            output.loc[selected] = branch.result
        # A matching outer branch consumes the row even when its nested block
        # yields no value; the following outer ELSEIF must not be evaluated.
        remaining &= ~mask
    if expression.otherwise is not None:
        if isinstance(expression.otherwise, CalculatedDimensionExpression):
            nested = _calculated_expression_values(frame, expression.otherwise)
            output.loc[remaining] = nested.loc[remaining]
        else:
            output.loc[remaining] = expression.otherwise
    return output


def _calculated_dimension_column(frame: pd.DataFrame, name: str, dimensions: Iterable[CalculatedDimension]) -> str | None:
    definition = next((item for item in dimensions if _normalise_catalog_name(item.name) == _normalise_catalog_name(name)), None)
    source = str(frame.attrs.get("catalogue_cdr_source") or "").casefold()
    if not definition or (source and source not in definition.sources):
        return None
    target = f"__catalog_calculated_{_normalise_catalog_name(definition.name)}"
    output = (
        _calculated_expression_values(frame, definition.expression)
        if definition.expression is not None
        else pd.Series(pd.NA, index=frame.index, dtype="string")
    )
    if definition.expression is None:
        for rule in definition.rules:
            mask = _calculated_conditions_mask(frame, rule.conditions)
            if mask is not None:
                output.loc[mask & output.isna()] = rule.value
    default_column = _column(frame, definition.default_from)
    if default_column:
        output = output.fillna(frame[default_column].astype("string"))
    if definition.default != "":
        output = output.fillna(definition.default)
    frame[target] = output
    return target


def materialize_calculated_dimensions(
    frame: pd.DataFrame, dimensions: Iterable[CalculatedDimension], cdr_source: str,
) -> pd.DataFrame:
    """Return CDR rows with every applicable workspace field as a physical column."""
    result = frame.copy()
    dimension_list = tuple(dimensions)
    calculated_keys = {_normalise_catalog_name(definition.name) for definition in dimension_list}
    stale_columns = [
        column for column in result.columns
        if _normalise_catalog_name(column) in calculated_keys
    ]
    if stale_columns:
        result = result.drop(columns=stale_columns)
    result.attrs["catalogue_calculated_dimensions"] = dimension_list
    result.attrs["catalogue_cdr_source"] = cdr_source
    for definition in dimension_list:
        if cdr_source.casefold() not in definition.sources:
            continue
        calculated = _calculated_dimension_column(result, definition.name, dimension_list)
        if calculated:
            result[definition.name] = result[calculated]
            result.drop(columns=[calculated], inplace=True)
    return result


def _catalog_column(
    frame: pd.DataFrame,
    name: str,
    multivendor: bool,
    metric: str | None = None,
    bucket_edges: list[float] | None = None,
    bucket_operator: str = "=",
    operator_as_vendor: bool = True,
) -> str | None:
    """Resolve a template field name against a source column or supported semantic dimension."""
    normalized = _normalise_catalog_name(name)
    calculated = _calculated_dimension_column(frame, name, frame.attrs.get("catalogue_calculated_dimensions", ()))
    if calculated:
        return calculated
    if normalized == "operator":
        return _group_column(frame, multivendor) if operator_as_vendor else _column(frame, ("Operator", "operator"))
    if normalized == "vendor":
        return _group_column(frame, multivendor) if multivendor else _column(frame, ("Vendor", "vendor"))
    if normalized == "vendorv3":
        # Tableau's Vendor_V3 calculation is materialised by ingestion as the
        # official combined Operator_Vendor value in ``Vendor``.
        return _column(frame, ("vendor", "Vendor"))
    if normalized == "lowratesession":
        rate = _column(frame, ("Mean_Data_Rate", "Mean Data Rate"))
        test = _column(frame, ("Test_Name", "Test Name"))
        if not rate or not test:
            return None
        rates = pd.to_numeric(frame[rate], errors="coerce")
        tests = frame[test].fillna("").astype(str).str.casefold()
        frame["__catalog_low_rate_session"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        downlink = tests.eq("fdtt http dl mt")
        uplink = tests.eq("fdtt udp ul st")
        frame.loc[downlink, "__catalog_low_rate_session"] = rates.loc[downlink].lt(100).astype("Int64")
        frame.loc[uplink, "__catalog_low_rate_session"] = rates.loc[uplink].lt(20).astype("Int64")
        return "__catalog_low_rate_session"
    if normalized in {"ltedlaggregatedbwmhz", "ltedltestbandwidthavgint"}:
        source = _column(frame, ("LTE_DL_Test_Bandwidth_Avg", "LTE DL Test Bandwidth Avg"))
        if not source:
            return None
        values = pd.to_numeric(frame[source], errors="coerce")
        frame["__catalog_lte_dl_aggregated_bw"] = values.map(
            lambda value: max(5, math.ceil(value / 5) * 5) if pd.notna(value) else pd.NA
        )
        return "__catalog_lte_dl_aggregated_bw"
    if normalized == "nrdlpcellnumerology1bandwidthnumber":
        source = _column(frame, ("NR_PCell_Numerology1_Bandwidth", "NR PCell Numerology1 Bandwidth"))
        if not source:
            return None
        extracted = frame[source].astype("string").str.split("->", n=1).str[0].str.extract(r"\[\s*([0-9.]+)\s*\]", expand=False)
        frame["__catalog_nr_numerology1_bandwidth"] = pd.to_numeric(extracted, errors="coerce")
        return "__catalog_nr_numerology1_bandwidth"
    if normalized == "nrultotalbandwidthmhz":
        source = _column(frame, ("NR_UL_RBs_Avg", "NR UL RBs Avg"))
        if not source:
            return None
        values = pd.to_numeric(frame[source], errors="coerce") * 12 * 30 / 1000
        frame["__catalog_nr_ul_total_bw"] = values.map(
            lambda value: max(5, math.ceil(value / 5) * 5) if pd.notna(value) else pd.NA
        )
        return "__catalog_nr_ul_total_bw"
    if normalized == "totalbwltenr":
        lte = _catalog_column(frame, "LTE DL Aggregated BW (MHz)", multivendor)
        nr = _column(frame, ("NR_DL_PCell_Bandwidth", "NR DL PCell Bandwidth"))
        if not lte and not nr:
            return None
        lte_values = pd.to_numeric(frame[lte], errors="coerce") if lte else pd.Series(0.0, index=frame.index)
        nr_values = pd.to_numeric(frame[nr], errors="coerce") if nr else pd.Series(0.0, index=frame.index)
        frame["__catalog_total_bw_lte_nr"] = lte_values.fillna(0) + nr_values.fillna(0)
        return "__catalog_total_bw_lte_nr"
    if normalized in {
        "emocnnnshystorical", "emocnnnshystoricalnew", "emocnnnshystoricalnew2",
        "emocnnnshystoricalwithoperator",
    }:
        test_time = _column(frame, ("Test_Start_Time", "Test Start Time"))
        nns_date = _column(frame, ("NNS Activation Date (F)", "NNS_Activation_Date_F"))
        mocn_date = _column(frame, ("MOCN Activation Date (F)", "MOCN_Activation_Date_F"))
        if not test_time or (not nns_date and not mocn_date):
            return None
        comparison = pd.to_datetime(frame[test_time], errors="coerce")
        if normalized != "emocnnnshystoricalnew2":
            campaign = _column(frame, ("Campaign", "campaign"))
            cutoffs = {
                "UK_Q4_2025_NSA": pd.Timestamp("2025-12-09"),
                "UK_Q1_2026": pd.Timestamp("2026-03-24"),
                "UK_Q2_2026": pd.Timestamp("2026-06-02"),
            }
            if campaign:
                comparison = frame[campaign].map(cutoffs).fillna(comparison)
        nns = pd.to_datetime(frame[nns_date], errors="coerce") if nns_date else pd.Series(pd.NaT, index=frame.index)
        mocn = pd.to_datetime(frame[mocn_date], errors="coerce") if mocn_date else pd.Series(pd.NaT, index=frame.index)
        result = pd.Series("Legacy", index=frame.index, dtype="string")
        result.loc[mocn.notna() & comparison.notna() & mocn.le(comparison)] = "eMOCN"
        result.loc[nns.notna() & comparison.notna() & nns.le(comparison)] = "NNS"
        if normalized == "emocnnnshystoricalwithoperator":
            host = _column(frame, ("Host Network", "Host_Network"))
            if host:
                mask = result.eq("eMOCN")
                result.loc[mask] = "eMOCN - " + frame.loc[mask, host].fillna("(blank)").astype(str)
        target = f"__catalog_{normalized}"
        frame[target] = result
        return target
    if normalized == "firstltepccarfcn":
        source = _column(frame, ("LTE_PCC_EARFCN", "LTE PCC EARFCN"))
        if not source:
            return None
        frame["__catalog_first_lte_pcc_arfcn"] = frame[source].astype("string").str.split("->", n=1).str[0].str.strip()
        return "__catalog_first_lte_pcc_arfcn"
    if normalized in {"tputabove", "tputbelow"}:
        rate_column = _column(frame, ("Mean_Data_Rate", "Mean Data Rate"))
        test_column = _column(frame, ("Test_Name", "Test Name"))
        if not rate_column or not test_column:
            return None
        rates = pd.to_numeric(frame[rate_column], errors="coerce")
        tests = frame[test_column].fillna("").astype(str).str.casefold()
        output = pd.Series(pd.NA, index=frame.index, dtype="string")
        downlink = tests.eq("fdtt http dl mt")
        uplink = tests.eq("fdtt udp ul st")
        if normalized == "tputabove":
            for mask, thresholds in (
                (downlink, ((100, "above100"), (20, "above20"), (5, "above5"), (2, "above2"), (0, "above 0"))),
                (uplink, ((20, "above20"), (10, "above10"), (3, "above3"), (1, "above1"), (0, "above0"))),
            ):
                remaining = mask & rates.notna()
                for threshold, label in thresholds:
                    selected = remaining & rates.gt(threshold)
                    output.loc[selected] = label
                    remaining &= ~selected
        else:
            for mask, thresholds, above in (
                (downlink, ((2, "below2"), (5, "below5"), (20, "below20"), (100, "below100")), 100),
                (uplink, ((1, "below1"), (3, "below3"), (10, "below10"), (20, "below20")), 20),
            ):
                remaining = mask & rates.notna()
                for threshold, label in thresholds:
                    selected = remaining & rates.lt(threshold)
                    output.loc[selected] = label
                    remaining &= ~selected
                output.loc[remaining & rates.gt(above)] = "Above"
        target = f"__catalog_{normalized}"
        frame[target] = output
        return target
    if normalized in {"ttfp10sratio", "ttfpgreaterthan10sratio"}:
        value_column = _column(frame, ("VideoStream_Time_to_First_Picture", "VideoStream Time to First Picture"))
        if not value_column:
            return None
        values = pd.to_numeric(frame[value_column], errors="coerce")
        frame["__catalog_ttfp_10s_ratio"] = values.map(
            lambda value: pd.NA if pd.isna(value) else ("Above 10s" if value >= 10 else "Below 10s")
        ).astype("string")
        return "__catalog_ttfp_10s_ratio"
    aliases = {
        "campaign": ("Campaign", "period", "Period", "Quarter"),
        "city": ("City", "city", "G_Level_1", "G_Level_2"),
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
        if bucket_edges and bucket_operator in {"<", "<="}:
            output = pd.Series(pd.NA, index=frame.index, dtype="string")
            remaining = numeric.notna()
            for threshold in bucket_edges:
                selected = remaining & (numeric.lt(threshold) if bucket_operator == "<" else numeric.le(threshold))
                output.loc[selected] = f"below{threshold:g}"
                remaining &= ~selected
            output.loc[remaining & numeric.gt(bucket_edges[-1])] = "Above"
            frame["__catalog_rate_bucket"] = output
            return "__catalog_rate_bucket"
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


def _latest_campaign_value(series: pd.Series) -> str | None:
    """Return the latest year/quarter campaign independently of its text format."""
    values = [value for value in series.dropna().astype(str).str.strip().unique() if value]
    if not values:
        return None
    return max(values, key=_campaign_sort_key)


def _campaign_sort_key(value: object) -> tuple[int, int, str]:
    """Sort campaign values chronologically when their year/quarter is present."""
    text = str(value).strip()
    year_match = re.search(r"(?:19|20)\d{2}", text)
    quarter_match = re.search(r"(?:^|[^A-Z0-9])Q\s*([1-4])(?:[^0-9]|$)", text, flags=re.I)
    return (
        int(year_match.group(0)) if year_match else -1,
        int(quarter_match.group(1)) if quarter_match else -1,
        text.casefold(),
    )


def _campaign_display_value(value: object) -> str:
    """Reduce NetCheck campaign identifiers to a stable year/quarter label."""
    return compact_campaign_value(value)


def _cdf_campaign_line_widths(
    series_campaigns: list[tuple[tuple[object, ...], Iterable[object]]],
    axis_columns: list[str],
    frame: pd.DataFrame,
) -> dict[tuple[str, ...], int]:
    """Rank CDF campaign weights independently inside each operator family."""
    labels = frame.attrs.get("catalogue_dimension_labels", {})

    def dimension_positions(name: str) -> list[int]:
        normalized_name = _normalise_catalog_name(name)
        positions: list[int] = []
        for index, column in enumerate(axis_columns):
            declared = labels.get(column, column)
            declared_names = declared if isinstance(declared, tuple) else (declared,)
            if any(_normalise_catalog_name(str(value)) == normalized_name for value in declared_names):
                positions.append(index)
        return positions

    operator_positions = dimension_positions("Operator")
    campaign_positions = dimension_positions("Campaign")
    normalized_rows: list[tuple[tuple[str, ...], set[str], tuple[str, ...]]] = []
    campaigns_by_family: dict[tuple[str, ...], set[str]] = {}
    for key, campaigns in series_campaigns:
        normalized_key = tuple(str(value) for value in key)
        normalized_campaigns = {
            _campaign_display_value(value)
            for value in campaigns
            if str(value).strip()
        }
        if operator_positions:
            family = tuple(normalized_key[index] for index in operator_positions)
        else:
            family = tuple(
                value for index, value in enumerate(normalized_key)
                if index not in campaign_positions
            )
        normalized_rows.append((normalized_key, normalized_campaigns, family))
        campaigns_by_family.setdefault(family, set()).update(normalized_campaigns)

    widths_by_family: dict[tuple[str, ...], dict[str, int]] = {}
    for family, campaigns in campaigns_by_family.items():
        ordered = sorted(campaigns, key=_campaign_sort_key)
        if len(ordered) <= 1:
            widths_by_family[family] = {campaign: 4 for campaign in ordered}
        elif len(ordered) == 2:
            widths_by_family[family] = {ordered[0]: 1, ordered[1]: 4}
        else:
            widths_by_family[family] = {
                campaign: max(1, 4 - recency_index)
                for recency_index, campaign in enumerate(reversed(ordered))
            }

    widths: dict[tuple[str, ...], int] = {}
    for key, campaigns, family in normalized_rows:
        family_widths = widths_by_family.get(family, {})
        widths[key] = max((family_widths.get(campaign, 1) for campaign in campaigns), default=4)
    return widths


def _apply_catalog_filters(frame: pd.DataFrame, entry: CatalogEntry, multivendor: bool, metric: str | None) -> pd.DataFrame:
    result = frame.copy()
    operator_mappings = result.attrs.get('operator_mappings', {})
    def mapped_operator(value: object) -> str:
        return _normalise_operator_label(value, operator_mappings)
    def mapped_vendor(value: object) -> str:
        return _normalise_vendor(value, operator_mappings)
    result.attrs["catalogue_calculated_dimensions"] = entry.calculated_dimensions
    result.attrs["catalogue_cdr_source"] = entry.cdr_source
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) in {"threshold", "buckets"}:
            continue
        # A Vendor Comparison materialises values as Operator_Vendor. Template
        # Operator filters therefore match that value's operator prefix (for
        # example Vodafone against Vodafone_Ericsson), while Vendor filters
        # still retain their native full-value semantics such as excluding
        # Mixed and Other vendor groups.
        normalized_condition = _normalise_catalog_name(condition.column)
        is_operator_filter = normalized_condition == "operator"
        is_vendor_filter = normalized_condition in {"vendor", "vendorv3"}
        column = _group_column(result, True) if multivendor and is_operator_filter else _catalog_column(
            result, condition.column, multivendor, metric, operator_as_vendor=False,
        )
        if not column:
            raise ValueError(f"Slide {entry.slide}: filter column '{condition.column}' does not exist in {entry.cdr_source}.")
        series = result[column]
        comparison_series = series.map(lambda value: _vendor_operator(value, operator_mappings)) if multivendor and is_operator_filter else (
            series if is_operator_filter else series
        )
        is_campaign_filter = normalized_condition == 'campaign'
        if is_campaign_filter:
            comparison_series = series.map(compact_campaign_value)
        def vendor_match(target: str, *, contains: bool = False) -> pd.Series:
            """Match a full Operator_Vendor value or an operator-independent vendor."""
            text = str(target).strip()
            # An underscore explicitly selects one materialised operator/vendor
            # value. A bare name selects that vendor beneath every operator.
            full_value = "_" in text
            candidates = series.map(lambda value: _normalise_vendor(value, operator_mappings)).astype(str) if full_value else series.map(lambda value: _vendor_label(value, result)).astype(str)
            expected = mapped_vendor(text) if full_value else text
            if contains:
                return candidates.str.contains(expected, case=False, na=False, regex=False)
            return candidates.str.casefold().eq(expected.casefold())
        if condition.operator in {">", ">=", "<", "<=", "=", "!="}:
            target = condition.values[0]
            if (
                _normalise_catalog_name(condition.column) == "campaign"
                and condition.operator in {"=", "!="}
                and _normalise_catalog_name(target) in {"latest", "latestcampaign"}
            ):
                latest_campaign = _latest_campaign_value(series)
                comparison = series.astype(str).eq(latest_campaign) if latest_campaign is not None else pd.Series(False, index=series.index)
                if condition.operator == "!=":
                    comparison = ~comparison
                result = result.loc[comparison].copy()
                continue
            if is_operator_filter:
                target = mapped_operator(target)
            elif is_campaign_filter:
                target = compact_campaign_value(target)
            numeric = pd.to_numeric(series, errors="coerce")
            target_number = pd.to_numeric(pd.Series([target]), errors="coerce").iloc[0]
            if pd.notna(target_number):
                comparison = {">": numeric > target_number, ">=": numeric >= target_number, "<": numeric < target_number, "<=": numeric <= target_number, "=": numeric == target_number, "!=": numeric != target_number}[condition.operator]
            else:
                if is_vendor_filter:
                    comparison = vendor_match(target)
                    if condition.operator == "!=":
                        comparison = ~comparison
                else:
                    comparison = {"=": comparison_series.astype(str).str.casefold() == target.casefold(), "!=": comparison_series.astype(str).str.casefold() != target.casefold()}.get(condition.operator)
                if comparison is None:
                    raise ValueError(f"Slide {entry.slide}: '{condition.operator}' requires a numeric value for '{condition.column}'.")
        elif condition.operator in {"CONTAINS", "NOT CONTAINS"}:
            targets = tuple(
                mapped_operator(item) if is_operator_filter else
                compact_campaign_value(item) if is_campaign_filter else item
                for item in condition.values
            )
            comparison = pd.Series(False, index=series.index)
            for target in targets:
                comparison |= vendor_match(target, contains=True) if is_vendor_filter else comparison_series.astype(str).str.contains(target, case=False, na=False, regex=False)
            if condition.operator == "NOT CONTAINS":
                comparison = ~comparison
        else:  # IN / NOT IN
            if is_vendor_filter:
                comparison = pd.Series(False, index=series.index)
                for target in condition.values:
                    comparison |= vendor_match(target)
            else:
                accepted = {
                    (mapped_operator(item) if is_operator_filter else
                     compact_campaign_value(item) if is_campaign_filter else item).casefold()
                    for item in condition.values
                }
                comparison = comparison_series.astype(str).str.casefold().isin(accepted)
            if condition.operator == "NOT IN":
                comparison = ~comparison
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


def _catalog_bucket_operator(entry: CatalogEntry) -> str:
    condition = next((
        item for item in parse_catalog_filters(entry.filters)
        if _normalise_catalog_name(item.column) == "buckets"
    ), None)
    return condition.operator if condition else "="


def _throughput_distribution_domain(frame: pd.DataFrame) -> list[str]:
    """Return Tableau's low-to-high legend domain for throughput buckets."""
    configured = frame.attrs.get("catalogue_distribution_buckets")
    if configured:
        return [str(value) for value in configured]
    if "__catalog_stack" not in frame:
        return []
    observed = [str(value) for value in frame["__catalog_stack"].dropna().unique()]
    if observed and all(value == "Above" or re.fullmatch(r"below\d+(?:\.\d+)?", value) for value in observed):
        below = sorted(
            (value for value in observed if value != "Above"),
            key=lambda value: float(value.removeprefix("below")),
        )
        return [*below, "Above"] if "Above" in observed else below
    return []


def _distribution_buckets(frame: pd.DataFrame, *, legend: bool = False) -> list[str]:
    """Resolve stable stack and legend orders for distribution charts."""
    domain = _throughput_distribution_domain(frame)
    if domain:
        return domain if legend else list(reversed(domain))
    if "__catalog_stack" not in frame:
        return []
    return [str(value) for value in frame["__catalog_stack"].dropna().drop_duplicates()]


def _distribution_bucket_colours(
    buckets: list[str], frame: pd.DataFrame,
) -> dict[tuple[object, ...], str]:
    """Use Tableau's semantic throughput palette or the normal category palette."""
    domain = _throughput_distribution_domain(frame)
    if domain and len(domain) == len(THROUGHPUT_DISTRIBUTION_COLORS):
        semantic = dict(zip(domain, THROUGHPUT_DISTRIBUTION_COLORS, strict=True))
        return {(bucket,): semantic[bucket] for bucket in buckets}
    return _series_colours([(bucket,) for bucket in buckets], ["__catalog_stack"], frame)


def _apply_catalog_grouping(frame: pd.DataFrame, entry: CatalogEntry, multivendor: bool, metric: str | None) -> tuple[pd.DataFrame, str, str]:
    frame.attrs["catalogue_calculated_dimensions"] = entry.calculated_dimensions
    frame.attrs["catalogue_cdr_source"] = entry.cdr_source
    row_spec = parse_catalog_grouping(entry.grouping_rows)
    column_spec = parse_catalog_grouping(entry.grouping_columns)
    bucket_edges = _catalog_bucket_edges(entry)
    bucket_operator = _catalog_bucket_operator(entry)
    # Multivendor data stores the effective comparison identity as one
    # ``Operator_Vendor`` field. Materialise its two display levels here so
    # every chart can render Vendor first and its individual Operators below.
    if multivendor:
        vendor = _group_column(frame, True)
        if vendor:
            mappings = frame.attrs.get('operator_mappings', {})
            frame["__catalog_multivendor_operator"] = frame[vendor].map(
                lambda value: _vendor_operator(value, mappings)
            )
            frame["__catalog_multivendor_vendor"] = frame[vendor].map(
                lambda value: _vendor_label(value, frame)
            )

    def resolve_dimensions(dimensions: tuple[str, ...], axis: str) -> list[str]:
        resolved: list[str] = []
        for dimension in dimensions:
            normalized = _normalise_catalog_name(dimension)
            if multivendor and normalized == "operator":
                column = "__catalog_multivendor_operator" if "__catalog_multivendor_operator" in frame else None
            elif multivendor and normalized == "vendor":
                column = "__catalog_multivendor_vendor" if "__catalog_multivendor_vendor" in frame else None
            else:
                column = _catalog_column(frame, dimension, multivendor, metric, bucket_edges, bucket_operator)
            if not column:
                raise ValueError(f"Slide {entry.slide}: {axis} grouping dimension '{dimension}' does not exist in {entry.cdr_source}.")
            resolved.append(column)
        return resolved

    row_columns = resolve_dimensions(row_spec.dimensions, "row")
    column_columns = resolve_dimensions(column_spec.dimensions, "column")
    explicit_dimension_values = {
        _normalise_catalog_name(condition.column): list(condition.values)
        for condition in parse_catalog_filters(entry.filters)
        if condition.operator == "IN"
    }
    configured_dimension_values: dict[str, list[str]] = {}
    operator_mappings = frame.attrs.get('operator_mappings', {})
    # Preserve every resolved hierarchy level for renderers that need pane-like
    # rows and nested column headers. The flattened primary/series fields remain
    # available for chart grammars that intentionally use compact labels.
    def materialise_dimension(dimension: str, column: str, target: str) -> None:
        values = frame[column].fillna("(blank)").astype(str)
        normalized_dimension = _normalise_catalog_name(dimension)
        if normalized_dimension == "campaign":
            campaign_labels = {value: _campaign_display_value(value) for value in values.unique()}
            values = values.map(campaign_labels)
        frame[target] = values
        requested = explicit_dimension_values.get(normalized_dimension)
        if requested:
            if normalized_dimension == "campaign":
                requested = sorted(
                    dict.fromkeys(_campaign_display_value(value) for value in requested),
                    key=_campaign_sort_key,
                )
            elif normalized_dimension == "operator":
                requested = [operator_mappings.get(str(value).strip().casefold(), str(value).strip()) for value in requested]
            configured_dimension_values[target] = list(dict.fromkeys(requested))

    row_display_columns: list[str] = []
    for index, (dimension, column) in enumerate(zip(row_spec.dimensions, row_columns, strict=True)):
        target = f"__catalog_row_{index}"
        materialise_dimension(dimension, column, target)
        row_display_columns.append(target)
    column_display_columns: list[str] = []
    for index, (dimension, column) in enumerate(zip(column_spec.dimensions, column_columns, strict=True)):
        target = f"__catalog_column_{index}"
        materialise_dimension(dimension, column, target)
        column_display_columns.append(target)
    # Rows form the category/table-row hierarchy. Columns form chart series and
    # table columns. Distribution charts reserve the final column level as the
    # stack/bucket breakdown and use any preceding column levels as the series.
    primary = "__catalog_primary"
    series = "__catalog_series"
    def materialise(columns: list[str], target: str) -> None:
        if not columns:
            frame[target] = "(all)"
        elif len(columns) == 1:
            frame[target] = frame[columns[0]].fillna("(blank)").astype(str)
        else:
            # On an empty frame pandas returns an empty DataFrame here rather
            # than an empty Series. Preserve a valid column so no-data chart
            # states do not interrupt the whole report.
            if frame.empty:
                frame[target] = pd.Series(index=frame.index, dtype="object")
            else:
                combined = frame[columns[0]].fillna("(blank)").astype(str)
                for column in columns[1:]:
                    combined = combined.str.cat(
                        frame[column].fillna("(blank)").astype(str),
                        sep=" · ",
                    )
                frame[target] = combined

    materialise(row_display_columns, primary)
    is_distribution = entry.chart_type.casefold() == "distribution stacked vertical bars"
    if is_distribution and column_display_columns:
        stack_column = column_display_columns[-1]
        series_columns = column_display_columns[:-1]
        materialise(series_columns, series)
        frame["__catalog_stack"] = frame[stack_column].fillna("(blank)").astype(str)
        if bucket_edges and bucket_operator in {"<", "<="}:
            frame.attrs["catalogue_distribution_buckets"] = [
                *(f"below{threshold:g}" for threshold in bucket_edges),
                "Above",
            ]
        elif domain := _throughput_distribution_domain(frame):
            frame.attrs["catalogue_distribution_buckets"] = domain
    else:
        materialise(column_display_columns, series)
    frame.attrs["catalogue_dimension_values"] = configured_dimension_values
    frame.attrs["catalogue_dimension_labels"] = {
        **{column: dimension for column, dimension in zip(row_display_columns, row_spec.dimensions, strict=True)},
        **{column: dimension for column, dimension in zip(column_display_columns, column_spec.dimensions, strict=True)},
        primary: row_spec.dimensions,
        series: column_spec.dimensions,
    }
    # Source tables are commonly appended newest campaign first. Whenever
    # Campaign participates in either aggregation axis, establish one shared
    # hierarchy order here so every chart grammar sees oldest -> newest while
    # retaining the first-seen order of all non-temporal dimensions.
    hierarchy = [
        *zip(row_display_columns, row_spec.dimensions, strict=True),
        *zip(column_display_columns, column_spec.dimensions, strict=True),
    ]
    campaign_columns = [
        column for column, dimension in hierarchy
        if _normalise_catalog_name(dimension) == "campaign"
    ]
    vendor_columns = [
        column for column, dimension in hierarchy
        if _normalise_catalog_name(dimension) == "vendor"
    ]
    split_vendor_hierarchy = multivendor and any(
        _normalise_catalog_name(dimension) == "operator" for _column_name, dimension in hierarchy
    )

    def vendor_sort_key(value: object) -> tuple[object, ...]:
        if split_vendor_hierarchy:
            return _multivendor_vendor_sort_key(value, frame)
        return _vendor_display_sort_key(value, frame)

    operator_columns = [
        column for column, dimension in hierarchy
        if _normalise_catalog_name(dimension) in {"operator", "subscriber"}
    ]
    needs_campaign_sort = any(
        (observed := frame[column].drop_duplicates().tolist()) != sorted(observed, key=_campaign_sort_key)
        for column in campaign_columns
    ) if not frame.empty else False
    needs_vendor_sort = any(
        (observed := frame[column].drop_duplicates().tolist()) != sorted(observed, key=vendor_sort_key)
        for column in vendor_columns
    ) if not frame.empty else False
    needs_operator_sort = any(
        (observed := frame[column].drop_duplicates().tolist()) != sorted(
            observed, key=lambda value: _operator_display_sort_key(value, frame),
        )
        for column in operator_columns
    ) if not frame.empty else False
    # Individually sorted Vendor and Operator domains can still be interleaved
    # in the source rows (for example Ericsson/VF, Huawei/VF, Ericsson/O2).
    # A multivendor hierarchy must therefore always receive the full stable
    # multi-column sort so Vendor remains the outer group in every renderer.
    if needs_campaign_sort or needs_vendor_sort or needs_operator_sort or split_vendor_hierarchy:
        sort_columns: list[str] = []
        for index, (column, dimension) in enumerate(hierarchy):
            values = frame[column].drop_duplicates().tolist()
            normalized_dimension = _normalise_catalog_name(dimension)
            if normalized_dimension == "campaign":
                values = sorted(values, key=_campaign_sort_key)
            elif normalized_dimension == "vendor":
                values = sorted(values, key=vendor_sort_key)
            elif normalized_dimension in {"operator", "subscriber"}:
                values = sorted(values, key=lambda value: _operator_display_sort_key(value, frame))
            configured_dimension_values[column] = list(values)
            ranks = {value: rank for rank, value in enumerate(values)}
            sort_column = f"__catalog_sort_{index}"
            frame[sort_column] = frame[column].map(ranks)
            sort_columns.append(sort_column)
        preserved_attrs = frame.attrs.copy()
        frame = frame.sort_values(sort_columns, kind="stable").drop(columns=sort_columns)
        frame.attrs = preserved_attrs
    return frame, primary, series


def preview_catalog_chart_data(
    frame: pd.DataFrame,
    entry: CatalogEntry,
    *,
    limit: int = 200,
    offset: int = 0,
    column_filters: dict[str, tuple[str, ...]] | None = None,
    include_filter_values: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return the exact, post-filter rows supplied to one template chart.

    This deliberately shares the reporting filter and grouping resolution so
    the editor can expose derived dimensions (for example ``Rate Bucket``)
    without asking users to reproduce report logic by hand.
    """
    if not entry.source_kind:
        raise ValueError('Only chart rows with a CDR source can be previewed.')
    spec = _catalog_spec(entry)
    metric = _metric_column(frame, spec)
    filtered = _apply_catalog_filters(frame, entry, False, metric)
    grouped, primary, series = _apply_catalog_grouping(filtered, entry, False, metric)
    display_columns: list[tuple[str, str]] = []

    def include(source: str | None, label: str) -> None:
        if source and source in grouped.columns:
            display_columns.append((source, label))

    # Include the physical/effective CDR fields referenced by every part of
    # the chart definition, not only the synthetic labels used by renderers.
    bucket_edges = _catalog_bucket_edges(entry)
    bucket_operator = _catalog_bucket_operator(entry)
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) not in {'threshold', 'buckets'}:
            include(_catalog_column(grouped, condition.column, False, metric, bucket_edges, bucket_operator, operator_as_vendor=False), f'Filter · {condition.column}')
    for axis, grouping in (('Rows Aggregation', entry.grouping_rows), ('Column Aggregation', entry.grouping_columns)):
        for dimension in parse_catalog_grouping(grouping).dimensions:
            include(_catalog_column(grouped, dimension, False, metric, bucket_edges, bucket_operator), f'{axis} · {dimension}')
    include(metric, f'KPI · {metric}' if metric else 'KPI')
    include(primary, 'Resolved Rows Aggregation')
    include(series, 'Resolved Column Aggregation')
    include('__catalog_stack', 'Resolved Stack Aggregation')

    # Legend contains source dimensions selected by the template/editor.
    legend_dimensions = ', '.join(_legend_dimensions(entry.legend)) or '(automatic)'
    if display_columns:
        full_result = pd.concat(
            [grouped[source].rename(label) for source, label in display_columns],
            axis=1,
        ).copy()
    else:
        full_result = grouped.copy()
    existing_identities = {column_identity(column) for column in full_result.columns}
    for source in grouped.columns:
        if str(source).startswith('__catalog_') or column_identity(source) in existing_identities:
            continue
        full_result[source] = grouped[source]
        existing_identities.add(column_identity(source))
    main_identities = [column_identity(column) for column in MAIN_CDR_FIELDS]
    ordered_columns: list[str] = []
    source_sheet = resolve_column_name(full_result.columns, 'source_sheet')
    if source_sheet:
        ordered_columns.append(source_sheet)
    for identity in main_identities:
        column = next((item for item in full_result.columns if column_identity(item) == identity), None)
        if column is not None and column not in ordered_columns:
            ordered_columns.append(column)
    ordered_columns.extend(column for column in full_result.columns if column not in ordered_columns)
    full_result = full_result[ordered_columns]
    full_result.insert(len(full_result.columns), 'Legend dimensions', legend_dimensions)
    filter_values = {
        str(column): sorted(
            {'' if pd.isna(value) else str(value) for value in full_result[column].tolist()},
            key=str.casefold,
        )
        for column in full_result.columns
    } if include_filter_values else {}
    for column, values in (column_filters or {}).items():
        resolved_column = resolve_column_name(full_result.columns, column)
        if resolved_column is None or not values:
            continue
        accepted = {str(value).strip().casefold() for value in values}
        full_result = full_result[
            full_result[resolved_column].map(
                lambda value: '' if pd.isna(value) else str(value).strip().casefold()
            ).isin(accepted)
        ]
    # Callers that render a table still request small pages.  The template-editor
    # preview also uses this helper to build one temporary, server-side result so
    # later page changes do not need to recalculate the chart filters.
    page_size = max(1, min(int(limit), 100_000))
    page_offset = max(0, int(offset))
    result = full_result.iloc[page_offset:page_offset + page_size].copy()
    return result, {
        'source_rows': len(frame.index),
        'matched_rows': len(filtered.index),
        'shown_rows': len(result.index),
        'visible_rows': len(full_result.index),
        'page_offset': page_offset,
        'columns': list(result.columns),
        'filter_values': filter_values,
    }


def render_catalog_chart_preview(
    frame: pd.DataFrame,
    entry: CatalogEntry,
    *,
    multivendor: bool = False,
    prefiltered: bool = False,
    renderer: str | None = None,
) -> bytes:
    """Render the same PNG chart used by a report for editor/report previews."""
    if not entry.source_kind:
        raise ValueError('Only chart rows with a CDR source can be previewed.')
    render_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
    render_frame = frame if prefiltered else normalise_operator_aliases(frame)
    if report_chart_renderer_name(renderer) == "dashboard-canvas":
        payload = catalog_chart_payload(
            render_frame,
            render_entry,
            multivendor=False,
            prefiltered=prefiltered,
        )
        return _render_dashboard_payload_png(payload)
    return _chart_for_catalog_entry(
        render_entry,
        {render_entry.source_kind: render_frame},
        multivendor,
        prefiltered=prefiltered,
    ).getvalue()


def render_catalog_chart_preview_with_hover(
    frame: pd.DataFrame,
    entry: CatalogEntry,
    *,
    multivendor: bool = False,
    prefiltered: bool = False,
    renderer: str | None = None,
) -> tuple[bytes, list[dict[str, object]]]:
    """Render one PNG and return hit geometry from the selected painter."""
    selected = report_chart_renderer_name(renderer)
    if selected != "dashboard-canvas":
        return (
            render_catalog_chart_preview(
                frame, entry, multivendor=multivendor, prefiltered=prefiltered, renderer=selected,
            ),
            catalog_chart_hover_targets(
                frame, entry, multivendor=multivendor, prefiltered=prefiltered,
            ),
        )
    if not entry.source_kind:
        raise ValueError('Only chart rows with a CDR source can be previewed.')
    render_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
    render_frame = frame if prefiltered else normalise_operator_aliases(frame)
    payload = catalog_chart_payload(
        render_frame, render_entry, multivendor=False, prefiltered=prefiltered,
    )
    image, hits = _render_dashboard_payload(payload)
    return image, _dashboard_hits_to_hover_targets(hits)


def catalog_chart_hover_targets(
    frame: pd.DataFrame, entry: CatalogEntry, *, multivendor: bool = False, prefiltered: bool = False,
) -> list[dict[str, object]]:
    """Describe interactive hit areas using the exact coordinate system of preview PNGs."""
    render_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
    spec = _catalog_spec(render_entry)
    if spec["kind"] == "multi_cdf":
        metric_targets: list[dict[str, object]] = []
        metrics = spec.get("metrics", ())
        columns = 2 if len(metrics) > 1 else 1
        rows = (len(metrics) + columns - 1) // columns
        cell_width = 1500 / columns
        cell_height = 820 / rows
        scale = min((cell_width - 18) / 1500, (cell_height - 10) / 900)
        rendered_width = 1500 * scale
        rendered_height = 900 * scale
        for index, candidate in enumerate(metrics):
            child = replace(
                render_entry,
                chart_title=candidate,
                kpi=candidate,
                chart_type="CDF Line",
            )
            offset_x = (index % columns) * cell_width + (cell_width - rendered_width) / 2
            offset_y = 80 + (index // columns) * cell_height + (cell_height - rendered_height) / 2
            for target in catalog_chart_hover_targets(frame, child, multivendor=multivendor, prefiltered=prefiltered):
                transformed = dict(target)
                for key in ("x", "width"):
                    if key in transformed:
                        transformed[key] = float(transformed[key]) * scale + (offset_x if key == "x" else 0)
                for key in ("y", "height"):
                    if key in transformed:
                        transformed[key] = float(transformed[key]) * scale + (offset_y if key == "y" else 0)
                if "points" in transformed:
                    transformed["points"] = [
                        [float(x) * scale + offset_x, float(y) * scale + offset_y]
                        for x, y in transformed["points"]
                    ]
                metric_targets.append(transformed)
        return metric_targets
    data = frame.copy() if prefiltered else normalise_operator_aliases(frame)
    try:
        if not prefiltered:
            data = _apply_catalog_filters(data, render_entry, multivendor, _metric_column(data, spec))
        data = _exclude_chart_values(data, render_entry, spec, multivendor)
        data, group, period = _apply_catalog_grouping(data, render_entry, multivendor, _metric_column(data, spec))
    except ValueError:
        return []
    metric = _metric_column(data, spec)
    legend_labels = _legend_labels(render_entry.legend)
    renderer_legend_position = parse_legend_position(render_entry.legend_position) if legend_labels else 'none'
    targets: list[dict[str, object]] = []

    def caption(key: tuple[object, ...], columns: list[str]) -> str:
        return _legend_key_caption(tuple(str(value) for value in key), columns, data, _legend_dimensions(render_entry.legend)) or 'Series'

    chart_type = render_entry.chart_type.casefold()
    hierarchy_columns = [column for column in data.columns if column.startswith('__catalog_row_') or column.startswith('__catalog_column_')]
    row_hierarchy = sorted(
        (column for column in hierarchy_columns if column.startswith('__catalog_row_')),
        key=lambda column: int(column.rsplit('_', 1)[1]),
    )
    column_hierarchy = sorted(
        (column for column in hierarchy_columns if column.startswith('__catalog_column_')),
        key=lambda column: int(column.rsplit('_', 1)[1]),
    )
    if spec['kind'] == 'failure_count' and group:
        status = _column(data, ('Call_Status', 'Test_Result', 'status'))
        if not status:
            return []
        failed = data[data[status].astype(str).str.contains('failed|drop|cutoff', case=False, na=False)].copy()
        failed['__catalog_failure_state'] = failed[status].astype(str).map(
            lambda value: 'Dropped' if 'drop' in value.casefold() else 'Failed'
        )
        if column_hierarchy or len(row_hierarchy) > 1:
            render_rows = row_hierarchy if column_hierarchy else []
            render_columns = column_hierarchy or row_hierarchy
            rows = _hierarchical_complete_keys(data, render_rows) if render_rows else [()]
            columns = _hierarchical_complete_keys(data, render_columns)
            if not rows or not columns:
                return []
            counts = failed.groupby([*render_rows, *render_columns, '__catalog_failure_state'], dropna=False).size()
            levels = list(range(len(render_rows) + len(render_columns)))
            maximum = max(int(counts.groupby(level=levels).sum().max()), 1) if not counts.empty else 1
            chart_left, chart_top, chart_height = 285, 245, 510
            chart_width = 980 if renderer_legend_position == 'right' else 1250
            row_height, column_width = chart_height / len(rows), chart_width / len(columns)
            active_columns = column_hierarchy or row_hierarchy
            for row_index, row_key in enumerate(rows):
                row_top = chart_top + row_index * row_height
                for column_index, column_key in enumerate(columns):
                    key_prefix = (*row_key, *column_key)
                    x = chart_left + column_index * column_width + 4
                    y = row_top + (row_height - max(12, min(22, row_height * .84))) / 2
                    height = max(12, min(22, row_height * .84))
                    label = ' · '.join(map(str, (*row_key, *column_key)))
                    for state_index, state in enumerate(('Failed', 'Dropped')):
                        value = int(counts.get((*key_prefix, state), 0))
                        width = max(column_width - 10, 1) * value / maximum
                        if width:
                            targets.append({'kind': 'bar', 'x': x, 'y': y, 'width': width, 'height': height, 'label': label, 'legend': _legend_caption(legend_labels, state_index, state), 'value': str(value)})
                        x += width
            return targets
        has_series = bool(period) and not data[period].fillna('(all)').astype(str).eq('(all)').all()
        fields = [group, period] if has_series else [group]
        counts = failed.groupby([*fields, '__catalog_failure_state'], dropna=False).size().unstack(fill_value=0)
        keys = _hierarchical_complete_keys(data, fields)
        index = pd.Index([key[0] for key in keys], name=fields[0]) if len(fields) == 1 else pd.MultiIndex.from_tuples(keys, names=fields)
        counts = counts.reindex(index, fill_value=0).head(16)
        maximum = max(int(counts.sum(axis=1).max()), 1) if not counts.empty else 1
        for row_index, (key, values) in enumerate(counts.iterrows()):
            key = key if isinstance(key, tuple) else (key,)
            x, y = 390, 120 + row_index * 42
            for state_index, state in enumerate(('Failed', 'Dropped')):
                value = int(values.get(state, 0)); width = int(980 * value / maximum)
                if width:
                    targets.append({'kind': 'bar', 'x': x, 'y': y, 'width': width, 'height': 25, 'label': ' · '.join(map(str, key)), 'legend': _legend_caption(legend_labels, state_index, state), 'value': str(value)})
                x += width
        return targets
    if spec['kind'] in {'status_100', 'quality_100'} and group and period:
        state_column = metric or _column(data, ('Call_Status', 'Test_Result', 'status'))
        if not state_column:
            return []
        state_data = data[[group, period, state_column, *hierarchy_columns]].dropna(subset=[group, period]).copy()
        state_data, states, _colours = _status_chart_categories(
            state_data, state_column, quality=spec['kind'] == 'quality_100', threshold=spec.get('threshold', 1.6),
        )
        if column_hierarchy or row_hierarchy:
            # Match the renderer: row dimensions remain on the left even when
            # there is no configured column hierarchy.
            render_rows = row_hierarchy
            active_columns = column_hierarchy
            if not active_columns:
                single_column = "__catalog_single_column"
                state_data[single_column] = "(all)"
                active_columns = [single_column]
            rows = _hierarchical_unique_keys(state_data, render_rows) if render_rows else [()]
            columns = _hierarchical_unique_keys(state_data, active_columns)
            if not rows or not columns:
                return []
            canvas, draw = _canvas('')
            row_label_font = _font(18, True)
            row_label_widths = [
                max((_text_width(draw, str(key[level])[:24], row_label_font) for key in rows), default=0) + 18
                for level in range(len(render_rows))
            ]
            chart_left = max(145, min(540, 24 + min(sum(row_label_widths), 420) + 68))
            row_height, column_width = 510 / len(rows), (1395 - chart_left) / len(columns)
            bar_width = max(18, min(86, column_width * 0.68))
            for row_index, row_key in enumerate(rows):
                row_mask = pd.Series(True, index=state_data.index); pane_top = 245 + row_index * row_height; pane_bottom = pane_top + row_height
                for field, value in zip(render_rows, row_key, strict=True): row_mask &= state_data[field].astype(str).eq(str(value))
                for column_index, column_key in enumerate(columns):
                    mask = row_mask.copy()
                    for field, value in zip(active_columns, column_key, strict=True): mask &= state_data[field].astype(str).eq(str(value))
                    subset = state_data.loc[mask]
                    if subset.empty: continue
                    x = chart_left + column_index * column_width + (column_width - bar_width) / 2; running = 0.0
                    for state in states:
                        value = float(subset['state'].eq(state).sum()) / len(subset); height = value * row_height; y = pane_bottom - running - height
                        label = ' · '.join(str(part) for part in (*row_key, *column_key) if str(part) != '(all)')
                        targets.append({'kind': 'bar', 'x': x, 'y': y, 'width': bar_width, 'height': height, 'label': label, 'legend': _legend_caption(legend_labels, states.index(state), state), 'value': f'{value:.1%}'})
                        running += height
            return targets
        combos = [(str(g), str(p)) for g, p in state_data[[group, period]].drop_duplicates().itertuples(index=False)]
        for index, key in enumerate(combos):
            subset = state_data[(state_data[group].astype(str) == key[0]) & (state_data[period].astype(str) == key[1])]; total = max(len(subset), 1); x = 145 + index * (1300 / len(combos)) + 12; running = 0
            for state in states:
                value = len(subset[subset['state'] == state]) / total; height = value * 640; y = 115 + 640 - running - height
                targets.append({'kind': 'bar', 'x': x, 'y': y, 'width': max(20, min(72, 1300 // max(len(combos) * 2, 1))), 'height': height, 'label': _catalogue_display_label(*key), 'legend': _legend_caption(legend_labels, states.index(state), state), 'value': f'{value:.1%}'})
                running += height
        return targets
    if chart_type == 'distribution stacked vertical bars' and group and period and '__catalog_stack' in data:
        data = data[data['__catalog_stack'].astype(str).ne('(blank)')]
        axes = _chart_axis_hierarchy(data, distribution=True) or [group, period]; combinations = _hierarchical_unique_keys(data, axes); buckets = _distribution_buckets(data)
        for index, key in enumerate(combinations):
            subset = data
            for column, value in zip(axes, key, strict=True): subset = subset[subset[column].astype(str) == str(value)]
            total = max(len(subset), 1); x = 125 + index * (1260 / len(combinations)) + 10; running = 0
            for bucket_index, bucket in enumerate(buckets):
                value = len(subset[subset['__catalog_stack'] == bucket]) / total; height = value * 475; y = 260 + 475 - running - height
                targets.append({'kind': 'bar', 'x': x, 'y': y, 'width': max(20, min(70, 1260 // max(len(combinations) * 2, 1))), 'height': height, 'label': ' · '.join(map(str, key)), 'legend': _legend_caption(legend_labels, bucket_index, bucket), 'value': f'{value:.1%}'})
                running += height
        return targets
    if 'vertical bars' in chart_type and group and metric:
        axes = _chart_axis_hierarchy(data) or ([group, period] if period and period != group else [group]); values = data[[*axes, metric]].copy(); values[metric] = pd.to_numeric(values[metric], errors='coerce'); grouped = values.dropna().groupby(axes, dropna=False, sort=False)[metric]; means = grouped.median() if chart_type == 'median vertical bars' else grouped.mean()
        maximum = max(float(means.max()), 1.0) if not means.empty else 1.0; bar_width = min(150, max(30, 1165 / max(len(means) * 1.7, 1)))
        for index, (key, value) in enumerate(means.items()):
            key = key if isinstance(key, tuple) else (key,); height = 400 * float(value) / maximum; x = 155 + (index + .5) * 1165 / len(means) - bar_width / 2
            targets.append({'kind': 'bar', 'x': x, 'y': 680 - height, 'width': bar_width, 'height': height, 'label': ' · '.join(map(str, key)), 'legend': caption(key, axes), 'value': f'{float(value):.2f}'})
        return targets
    if spec['kind'] == 'cdf_mean' and group and metric:
        axes = _chart_axis_hierarchy(data) or [group, *([period] if period and period != group else [])]; values = data[[*axes, metric]].copy(); values[metric] = pd.to_numeric(values[metric], errors='coerce'); values = values.dropna()
        if values.empty: return []
        low, observed_high = float(values[metric].min()), float(values[metric].max())
        series_values = []
        for key in _hierarchical_unique_keys(values, axes):
            subset = values
            for column, value in zip(axes, key, strict=True): subset = subset[subset[column].astype(str) == str(value)]
            ordered = sorted(subset[metric].tolist())
            if ordered:
                series_values.append((key, ordered))
        automatic_high = _cdf_terminal_x_maximum([ordered for _, ordered in series_values], low, observed_high)
        automatic_high = automatic_high if automatic_high > low else low + 1
        (low, high), (y_low, y_high) = _cdf_domains(
            low, automatic_high, render_entry.axis_x_range, render_entry.axis_y_range,
        )
        left, top, width, height = _cdf_plot_geometry(parse_legend_position(render_entry.legend_position))
        for key, ordered in series_values:
            visible_points = [
                point for point in _cdf_visible_points(ordered, low, high)
                if y_low <= point[1] <= y_high
            ]
            if not visible_points:
                continue
            series = caption(key, axes)
            # A CDF can contain millions of source samples. Its PNG is a
            # continuous line, so a bounded set of evenly spaced vertices is
            # sufficient for hit testing and avoids a huge delayed JSON reply.
            sample_count = min(len(visible_points), MAX_CDF_HOVER_TARGETS_PER_SERIES)
            indexes = range(len(visible_points)) if sample_count == len(visible_points) else sorted({round(index * (len(visible_points) - 1) / (sample_count - 1)) for index in range(sample_count)})
            for index in indexes:
                value, cumulative = visible_points[index]
                targets.append({'kind': 'line', 'series': '\x1f'.join(map(str, key)), 'x': left + (value - low) / (high - low) * width, 'y': top + height - (cumulative - y_low) / (y_high - y_low) * height, 'label': metric.replace('_', ' '), 'legend': series, 'value': f'{value:.2f}', 'cumulative': f'{cumulative:.1%}'})
    return targets


def is_empty_catalog_chart(image: bytes, entry: CatalogEntry) -> bool:
    """Identify the intentional no-samples placeholder emitted by the renderer."""
    title = entry.chart_title or entry.slide_title
    return image in {_empty_chart(title).getvalue(), render_unavailable_source_chart(entry)}


def render_unavailable_source_chart(
    entry: CatalogEntry,
    message: str | None = None,
    *,
    width: int = 1600,
    height: int = 900,
) -> bytes:
    """Render a stable placeholder when a chart source or definition is unavailable."""
    title = entry.chart_title or entry.slide_title
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    scale = min(width / 1600, height / 900)
    draw.text((round(width * .02), round(height * .02)), title, fill="#1D3345", font=_font(max(16, round(40 * scale)), True))
    draw.text(
        (round(width * .03), round(height * .49)),
        message or f"Unavailable source type: {entry.cdr_source}",
        fill="#61727D", font=_font(max(12, round(24 * scale))),
    )
    output = BytesIO(); image.save(output, format="PNG")
    return output.getvalue()


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
    metric = _column(frame, spec.get("metric", ()))
    if metric:
        return metric
    for candidate in spec.get("metric", ()):
        resolved = _catalog_column(frame, candidate, False)
        if resolved:
            return resolved
    return None


def _mapping_groups(frame: pd.DataFrame | None, mapping_type: str) -> list[dict[str, object]]:
    if frame is None:
        return []
    groups = frame.attrs.get(f'{mapping_type}_mapping_groups', [])
    return groups if isinstance(groups, list) else []


def _mapping_group(value: object, mapping_type: str, frame: pd.DataFrame | None) -> dict[str, object] | None:
    normalized = str(value or '').strip().casefold()
    for group in _mapping_groups(frame, mapping_type):
        labels = [group.get('canonical'), *(group.get('aliases') or [])]
        if normalized in {str(label or '').strip().casefold() for label in labels}:
            return group
    return None


def _mapping_prefix_group(
    value: object, mapping_type: str, frame: pd.DataFrame | None,
) -> dict[str, object] | None:
    """Return the longest configured identity prefix in a composite label."""
    normalized = str(value or '').strip().casefold()
    matches: list[tuple[int, dict[str, object]]] = []
    for group in _mapping_groups(frame, mapping_type):
        labels = [group.get('canonical'), *(group.get('aliases') or [])]
        for label in labels:
            candidate = str(label or '').strip().casefold()
            if not candidate or not normalized.startswith(candidate):
                continue
            remainder = normalized[len(candidate):]
            if not remainder or re.match(r'^\s*[_·|/]', remainder):
                matches.append((len(candidate), group))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _operator_colour(label: object, frame: pd.DataFrame | None = None) -> str | None:
    """Return the workspace theme colour for an Operator identity."""
    text = str(label or '').strip()
    group = _mapping_group(text, 'operator', frame)
    if group is None:
        group = _mapping_prefix_group(text, 'operator', frame)
    return str(group.get('color')) if group and group.get('color') else None


def _colour(label: object, index: int = 0) -> str:
    """Return a neutral series colour unless a renderer opts into a palette."""
    return NEUTRAL_SERIES_COLORS[index % len(NEUTRAL_SERIES_COLORS)]


OUTCOME_COLOUR_VARIANTS = {
    "success": ("#2C9A62", "#197A4A", "#56B881", "#0F5C35"),
    "failure": ("#C83E4D", "#D8555F", "#E26A70", "#AE2F42", "#F08A8F", "#8F2035"),
}


def _outcome_kind(value: object) -> str | None:
    """Classify a result label as a success or failure without fixing its shade."""
    if value is None or value is pd.NA:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    # Check negative language first because "unsuccessful" also contains
    # the success token.
    if re.search(r"fail|error|drop|cutoff|unsuccess|incomplete|abort|cancel|timeout|reject|denied", text):
        return "failure"
    if re.search(r"success|complete|pass|\bok\b|healthy|available", text):
        return "success"
    return None


def _outcome_colour(value: object) -> str | None:
    """Return the primary conventional colour for a semantic outcome label."""
    kind = _outcome_kind(value)
    return OUTCOME_COLOUR_VARIANTS[kind][0] if kind else None


def _colour_variants(color: str) -> tuple[str, ...]:
    """Build contrasting shades around one Admin-selected theme colour."""
    try:
        red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return (str(color),)
    def blend(target: int, ratio: float) -> str:
        channels = [round(channel + (target - channel) * ratio) for channel in (red, green, blue)]
        return '#' + ''.join(f'{channel:02X}' for channel in channels)
    return color.upper(), blend(0, .38), blend(255, .34), blend(0, .2)


def _hierarchy_group_colours(
    keys: list[tuple[object, ...]], level: int = 0, frame: pd.DataFrame | None = None,
) -> dict[str, str]:
    """Colour one hierarchy level consistently, with readable variants."""
    colours: dict[str, str] = {}
    offsets: dict[str, int] = {}
    neutral_index = 0
    for key in keys:
        group = str(key[level]) if len(key) > level else ""
        if group in colours:
            continue
        base = _operator_colour(group, frame)
        if base:
            offset = offsets.get(base, 0)
            variants = _colour_variants(base)
            colours[group] = variants[offset % len(variants)]
            offsets[base] = offset + 1
        else:
            # Use the category's position among neutral groups. The same
            # dimension may reach the renderer as Operator x Campaign while
            # its legend contains each Operator only once; a global bar index
            # assigned different colours to the same label in those two lists.
            colours[group] = _colour(group, neutral_index)
            neutral_index += 1
    return colours


def _dimension_roles(frame: pd.DataFrame, axis_columns: list[str]) -> list[set[str]]:
    """Identify the declared Operator/Vendor roles behind materialised axes."""
    definitions = frame.attrs.get("catalogue_dimension_labels", {})
    roles: list[set[str]] = []
    for column in axis_columns:
        definition = definitions.get(column, column)
        labels = definition if isinstance(definition, (tuple, list)) else (definition,)
        normalised = {_normalise_catalog_name(str(label)) for label in labels}
        roles.append({
            role for role in ("operator", "vendor")
            if any(role in label or (role == 'operator' and 'subscriber' in label) for label in normalised)
        })
    return roles


def _vendor_label(value: object, frame: pd.DataFrame | None = None) -> str:
    """Extract everything after the longest configured Operator prefix."""
    text = str(value).strip()
    if _mapping_group(text, 'operator', frame):
        return text
    prefix_matches: list[str] = []
    for group in _mapping_groups(frame, 'operator'):
        for label in [group.get('canonical'), *(group.get('aliases') or [])]:
            candidate = str(label or '').strip()
            if not candidate or not text.casefold().startswith(candidate.casefold()):
                continue
            remainder = text[len(candidate):]
            if re.match(r'^\s*[_·|/]', remainder):
                prefix_matches.append(candidate)
    if prefix_matches:
        prefix = max(prefix_matches, key=len)
        remainder = text[len(prefix):]
        return re.sub(r'^\s*[_·|/]\s*', '', remainder, count=1).strip()
    parts = [part.strip() for part in re.split(r"[_·|/]", text) if part.strip()]
    return parts[-1] if parts else str(value).strip()


def _vendor_colour(vendor: object, frame: pd.DataFrame | None) -> str | None:
    group = _mapping_group(_vendor_label(vendor, frame), 'vendor', frame)
    return str(group.get('color')) if group and group.get('color') else None


def _operator_display_sort_key(value: object, frame: pd.DataFrame | None = None) -> tuple[int, str]:
    """Order configured operators before unknown labels."""
    normalized = _operator_sort_label(value)
    group = _mapping_group(normalized, 'operator', frame) or _mapping_prefix_group(normalized, 'operator', frame)
    rank = int(group.get('position', 0)) if group else len(_mapping_groups(frame, 'operator'))
    label = str(group.get('canonical')) if group else normalized
    return rank, label.casefold()


def _vendor_display_sort_key(value: object, frame: pd.DataFrame | None = None) -> tuple[int, str, int, str]:
    """Order ``Operator_Vendor`` values from the two Admin mapping tables."""
    text = str(value).strip()
    operator_group = _mapping_prefix_group(text, 'operator', frame)
    normalized_operator = str(operator_group.get('canonical')) if operator_group else _operator_sort_label(text)
    normalized_vendor = _vendor_label(text, frame).casefold()
    vendor_group = _mapping_group(normalized_vendor, 'vendor', frame)
    vendor_rank = int(vendor_group.get('position', 0)) if vendor_group else len(_mapping_groups(frame, 'vendor'))
    operator_rank, operator_label = _operator_display_sort_key(normalized_operator, frame)
    return operator_rank, operator_label, vendor_rank, normalized_vendor


def _multivendor_vendor_sort_key(value: object, frame: pd.DataFrame | None = None) -> tuple[object, ...]:
    """Order real Vendors first and Operator-only identities last."""
    text = str(value).strip()
    vendor = _vendor_label(text, frame)
    vendor_group = _mapping_group(vendor, 'vendor', frame)
    exact_operator = _mapping_group(text, 'operator', frame)
    if exact_operator or text.casefold() in {'', '(blank)', 'blank', 'none', 'n/a', 'na'}:
        operator_rank, operator_label = _operator_display_sort_key(text, frame)
        return 2, operator_rank, operator_label
    if vendor_group:
        operator_rank, operator_label = _operator_display_sort_key(text, frame)
        return (
            0, int(vendor_group.get('position', 0)),
            str(vendor_group.get('canonical') or vendor).casefold(), operator_rank, operator_label,
        )
    # Preserve unconfigured but genuine Vendor labels after the configured
    # Vendor Mapping domain and before identities that have no Vendor.
    return 1, vendor.casefold(), text.casefold()


def _series_colours(
    keys: list[tuple[object, ...]],
    axis_columns: list[str],
    frame: pd.DataFrame,
    *,
    line_chart: bool = False,
) -> dict[tuple[object, ...], str]:
    """Choose colours from declared dimensions rather than label coincidences.

    Vendor is the stable visual identity for bars, points, stacks and lines.
    Recognised vendors use their exact thematic colour regardless of operator.
    Line charts distinguish operators through stroke patterns instead of
    introducing additional shades of the same vendor colour.
    """
    if not keys:
        return {}

    def semantic_outcome(key: tuple[object, ...]) -> tuple[str, str] | None:
        for value in reversed(key):
            kind = _outcome_kind(value)
            if kind:
                return kind, str(value)
        return None

    semantic_outcomes = {key: semantic_outcome(key) for key in keys}
    # Result/Status series have semantic meaning that takes precedence over
    # the neutral palette, regardless of chart grammar or aggregation axis.
    # Different outcome labels retain distinct shades within their semantic
    # family, while repeated labels stay visually stable across campaigns.
    if all(semantic_outcomes.values()):
        colours: dict[tuple[object, ...], str] = {}
        assigned: dict[tuple[str, str], str] = {}
        offsets = {"success": 0, "failure": 0}
        for key in keys:
            outcome = semantic_outcomes[key]
            assert outcome is not None
            kind, label = outcome
            identity = (kind, label.casefold())
            if identity not in assigned:
                variants = OUTCOME_COLOUR_VARIANTS[kind]
                assigned[identity] = variants[offsets[kind] % len(variants)]
                offsets[kind] += 1
            colours[key] = assigned[identity]
        return colours
    roles = _dimension_roles(frame, axis_columns)
    operator_levels = [index for index, role in enumerate(roles) if "operator" in role]
    vendor_levels = [index for index, role in enumerate(roles) if "vendor" in role]
    identity_levels = list(dict.fromkeys([*operator_levels, *vendor_levels]))
    operator_level = next(
        (index for index in identity_levels if any(_operator_colour(key[index], frame) for key in keys if len(key) > index)),
        None,
    )
    operator_for_key = {
        key: next(
            (str(key[index]) for index in identity_levels if len(key) > index and _operator_colour(key[index], frame)),
            "",
        )
        for key in keys
    }
    operator_values = {colour for key in keys if (colour := _operator_colour(operator_for_key[key], frame))}

    if vendor_levels:
        vendor_level = vendor_levels[0]
        vendor_keys = [_vendor_label(key[vendor_level], frame) if len(key) > vendor_level else "" for key in keys]
        vendor_colours: dict[str, str] = {}
        neutral_index = 0
        for key, vendor in zip(keys, vendor_keys, strict=True):
            missing_vendor = vendor.strip().casefold() in {'', '(blank)', 'blank', 'none', 'n/a', 'na'}
            identity = (
                f"operator:{operator_for_key[key].casefold()}" if missing_vendor and operator_for_key[key]
                else vendor.casefold()
            )
            if identity in vendor_colours:
                continue
            vendor_group = _mapping_group(vendor, 'vendor', frame)
            operator_base = _operator_colour(operator_for_key[key], frame) or _operator_colour(key[vendor_level], frame)
            base = (
                operator_base if missing_vendor and operator_base
                else str(vendor_group.get('color')) if vendor_group and vendor_group.get('color')
                else operator_base
            )
            if base:
                vendor_colours[identity] = base.upper()
            else:
                vendor_colours[identity] = _colour(vendor, neutral_index)
                neutral_index += 1
        return {
            key: vendor_colours[
                f"operator:{operator_for_key[key].casefold()}"
                if vendor.strip().casefold() in {'', '(blank)', 'blank', 'none', 'n/a', 'na'} and operator_for_key[key]
                else vendor.casefold()
            ]
            for key, vendor in zip(keys, vendor_keys, strict=True)
        }

    if operator_level is not None and (len(operator_values) > 1 or line_chart):
        vendor_level = vendor_levels[0] if vendor_levels else operator_level
        palette_keys = []
        for key in keys:
            identity = (
                f"{operator_for_key[key]} · {_vendor_label(key[vendor_level], frame)}"
                if len(key) > vendor_level else operator_for_key[key]
            )
            palette_keys.append(identity)
        palette = _hierarchy_group_colours([(value,) for value in palette_keys], frame=frame)
        return {key: palette[palette_key] for key, palette_key in zip(keys, palette_keys, strict=True)}

    # Keep a non-semantic category stable across subordinate dimensions such
    # as Campaign. Legends contain each primary category once, whereas bars or
    # lines may contain several hierarchy combinations for that category.
    primary_colours = _hierarchy_group_colours(keys, frame=frame)
    return {key: primary_colours[str(key[0]) if key else ""] for key in keys}


CDF_COMPARISON_LINE_DASHES: tuple[tuple[int, ...], ...] = (
    (), (18, 8), (2, 10), (18, 6, 3, 6), (10, 7), (22, 6, 2, 6, 2, 6),
)


def _series_line_dashes(
    keys: list[tuple[object, ...]], axis_columns: list[str], frame: pd.DataFrame,
) -> dict[tuple[object, ...], tuple[int, ...]]:
    """Distinguish Operators within each Vendor, starting with a solid line."""
    roles = _dimension_roles(frame, axis_columns)
    operator_levels = [index for index, role in enumerate(roles) if "operator" in role]
    vendor_levels = [index for index, role in enumerate(roles) if "vendor" in role]
    identity_levels = list(dict.fromkeys([*operator_levels, *vendor_levels]))
    if not vendor_levels:
        return {key: () for key in keys}

    identities: dict[tuple[object, ...], tuple[str, str | None]] = {}
    vendor_operators: dict[str, set[str]] = {}
    for key in keys:
        operator_group = None
        operator_label = ""
        for index in identity_levels:
            if index >= len(key):
                continue
            value = str(key[index])
            operator_group = _mapping_group(value, 'operator', frame) or _mapping_prefix_group(value, 'operator', frame)
            if operator_group:
                operator_label = str(operator_group.get('canonical') or value).casefold()
                break
        if not operator_label:
            operator_label = str(key[operator_levels[0]] if operator_levels else key[0]).casefold()

        vendor_value = str(key[vendor_levels[0]]) if vendor_levels[0] < len(key) else ""
        vendor = _vendor_label(vendor_value, frame).strip()
        missing_vendor = (
            vendor.casefold() in {'', '(blank)', 'blank', 'none', 'n/a', 'na', operator_label}
            or _mapping_group(vendor_value, 'operator', frame) is not None
        )
        vendor_identity = None if missing_vendor else vendor.casefold()
        identities[key] = operator_label, vendor_identity
        if vendor_identity is not None:
            vendor_operators.setdefault(vendor_identity, set()).add(operator_label)

    configured_operators = {
        str(group.get('canonical') or '').strip().casefold(): int(group.get('position', 0))
        for group in _mapping_groups(frame, 'operator')
    }
    operator_patterns: dict[str, dict[str, tuple[int, ...]]] = {}
    for vendor, operators in vendor_operators.items():
        ordered = sorted(
            operators,
            key=lambda operator: (configured_operators.get(operator, len(configured_operators)), operator),
        )
        operator_patterns[vendor] = {
            operator: CDF_COMPARISON_LINE_DASHES[index % len(CDF_COMPARISON_LINE_DASHES)]
            for index, operator in enumerate(ordered)
        }

    dashes: dict[tuple[object, ...], tuple[int, ...]] = {}
    for key, (operator, vendor) in identities.items():
        dashes[key] = operator_patterns.get(vendor or '', {}).get(operator, ())
    return dashes


def _operator_hierarchy_level(keys: list[tuple[object, ...]], axis_columns: list[str]) -> int:
    """Find the column-aggregation level carrying operator/vendor identity."""
    candidates = [
        index for index, column in enumerate(axis_columns)
        if column.startswith("__catalog_column_")
    ]
    if not candidates:
        return 0
    # Templates may declare Campaign before Operator/Vendor. Prefer whichever
    # column level actually carries recognised operator identity, while keeping
    # the declared order as the deterministic fallback.
    return max(
        candidates,
        key=lambda index: (sum(_operator_colour(key[index]) is not None for key in keys if len(key) > index), -index),
    )


def _operator_vendor_key(*labels: object) -> str:
    """Choose the operator/vendor portion of a composite chart label."""
    for label in labels:
        for part in re.split(r"\s*·\s*", str(label)):
            if _operator_colour(part):
                return part.strip()
    return str(labels[0]).strip() if labels else ""


def _legend_dimensions(value: str) -> tuple[str, ...]:
    """Return the ordered CDR dimensions selected in the Legend field."""
    if "/" in value:
        return ()
    return tuple(dimension.strip() for dimension in value.split(",") if dimension.strip())


def _legend_labels(value: str) -> tuple[str, ...]:
    """Return legacy/manual legend captions separated with slashes."""
    if "/" not in value:
        return ()
    return tuple(label.strip() for label in value.split("/") if label.strip())


def _legend_key_caption(
    key: tuple[object, ...],
    axis_columns: list[str],
    frame: pd.DataFrame,
    dimensions: tuple[str, ...],
) -> str:
    """Build a caption from the selected dimensions represented by an axis key."""
    requested = {_normalise_catalog_name(value) for value in dimensions}
    labels = frame.attrs.get("catalogue_dimension_labels", {})
    selected_parts: list[str] = []
    for index, column in enumerate(axis_columns):
        declared = labels.get(column, column)
        declared_names = declared if isinstance(declared, tuple) else (declared,)
        declared_normalized = {_normalise_catalog_name(str(name)) for name in declared_names}
        if declared_normalized & requested:
            selected_parts.append(str(key[index]))
    parts = selected_parts or [str(value) for value in key if str(value) != "(all)"]
    return " · ".join(parts) or "(all)"


def _legend_caption(labels: tuple[str, ...], index: int, fallback: object) -> str:
    return labels[index] if index < len(labels) else str(fallback)


def _resolved_legend_items(
    entry: CatalogEntry,
    frame: pd.DataFrame,
    metric: str | None,
) -> list[tuple[str, str, int]]:
    """Resolve the Legend field against chart dimensions or active filters.

    A chart dimension/KPI produces a conventional coloured value legend.  A
    field used only by a filter produces a text-only description of that
    filter.  This keeps the template field authoritative instead of allowing
    individual renderers to invent an unrelated legend.
    """
    requested = _legend_dimensions(entry.legend)
    if not requested:
        return []
    if (
        entry.chart_type.strip().casefold() == "threshold stacked vertical bars"
        and any(_normalise_catalog_name(value) == "threshold" for value in requested)
    ):
        threshold = _catalog_threshold(entry)
        threshold_caption = f"{threshold:g}"
        return [
            (f"< {threshold_caption}", "#E15759", 2),
            (f"≥ {threshold_caption}", "#59A14F", 2),
        ]
    row_dimensions = parse_catalog_grouping(entry.grouping_rows).dimensions
    column_dimensions = parse_catalog_grouping(entry.grouping_columns).dimensions
    kpi_dimensions = catalog_kpi_fields(entry.kpi)
    chart_names = {
        _normalise_catalog_name(value)
        for value in (*row_dimensions, *column_dimensions, *kpi_dimensions)
    }
    chart_fields = [value for value in requested if _normalise_catalog_name(value) in chart_names]

    is_distribution = entry.chart_type.strip().casefold() == "distribution stacked vertical bars"
    bucket_names = {"bucket", "buckets", "ratebucket", "valuebucket"}
    bucket_legend_requested = is_distribution and any(
        _normalise_catalog_name(value) in bucket_names for value in requested
    )

    labels = frame.attrs.get("catalogue_dimension_labels", {})
    resolved_columns: list[str] = []
    for field in chart_fields:
        normalized = _normalise_catalog_name(field)
        column = next((
            candidate for candidate, declared in labels.items()
            if any(_normalise_catalog_name(str(name)) == normalized for name in (declared if isinstance(declared, tuple) else (declared,)))
        ), None)
        if column is None and metric and _normalise_catalog_name(metric) == normalized:
            column = metric
        if column is None:
            column = next(
                (candidate for candidate in frame.columns if _normalise_catalog_name(str(candidate)) == normalized),
                None,
            )
        if column and column not in resolved_columns:
            resolved_columns.append(column)

    items: list[tuple[str, str, int]] = []
    is_cdf = "cdf" in entry.chart_type.casefold()
    axis_columns = _chart_axis_hierarchy(frame)
    if bucket_legend_requested and "__catalog_stack" in frame.columns:
        buckets = _distribution_buckets(frame, legend=True)
        bucket_colours = _distribution_bucket_colours(buckets, frame)
        items.extend(
            (str(bucket), bucket_colours.get((bucket,), _colour(bucket, index)), 2)
            for index, bucket in enumerate(buckets)
        )
    elif is_cdf and chart_fields and axis_columns:
        combinations = _hierarchical_unique_keys(frame, axis_columns)
        colours = _series_colours(combinations, axis_columns, frame, line_chart=True)
        grouper = axis_columns[0] if len(axis_columns) == 1 else axis_columns
        grouped_subsets = {
            tuple(str(value) for value in (key if isinstance(key, tuple) else (key,))): subset
            for key, subset in frame.groupby(grouper, sort=False, dropna=False)
        }
        campaign_column = _period_column(frame)
        series_campaigns = []
        for combination in combinations:
            subset = grouped_subsets.get(tuple(str(value) for value in combination), frame.iloc[0:0])
            subset_campaigns = (
                subset[campaign_column].dropna().astype(str).map(_campaign_display_value).unique()
                if campaign_column else ()
            )
            series_campaigns.append((combination, subset_campaigns))
        line_widths = _cdf_campaign_line_widths(series_campaigns, axis_columns, frame)
        for index, combination in enumerate(combinations):
            width = line_widths.get(tuple(str(value) for value in combination), 4)
            caption = _legend_key_caption(combination, axis_columns, frame, tuple(chart_fields))
            items.append((caption, colours.get(combination, _colour(caption, index)), width))
    elif (
        resolved_columns
        and metric
        and resolved_columns[0] == metric
        and ("100%" in entry.chart_type.casefold() or entry.chart_type.casefold() == "threshold stacked vertical bars")
    ):
        _state_data, states, colours = _status_chart_categories(
            frame[[metric]].copy(), metric,
            quality=entry.chart_type.casefold() == "threshold stacked vertical bars",
            threshold=_catalog_threshold(entry),
        )
        items.extend((state, colour, 2) for state, colour in zip(states, colours, strict=True))
    elif resolved_columns:
        values = frame[resolved_columns].dropna().drop_duplicates()
        legend_keys = [key if isinstance(key, tuple) else (key,) for key in values.itertuples(index=False, name=None)]
        legend_colours = _series_colours(legend_keys, resolved_columns, frame)
        for index, values_tuple in enumerate(values.itertuples(index=False, name=None)):
            caption = " · ".join(str(value) for value in values_tuple)
            colour = (
                legend_colours.get(legend_keys[index])
                or _outcome_colour(caption)
                or _operator_colour(caption, frame)
                or _colour(caption, index)
            )
            items.append((caption, colour, 2))

    filter_names = {
        _normalise_catalog_name(value)
        for value in requested
        if _normalise_catalog_name(value) not in chart_names
        and not (bucket_legend_requested and _normalise_catalog_name(value) in bucket_names)
    }
    for condition in parse_catalog_filters(entry.filters):
        if _normalise_catalog_name(condition.column) not in filter_names:
            continue
        values = ", ".join(condition.values)
        if condition.operator in {"IN", "NOT IN"} or len(condition.values) > 1:
            values = f"({values})"
        items.append((f"{condition.column} {condition.operator} {values}", "", 0))
    return items


def _apply_resolved_legend(
    chart: BytesIO,
    entry: CatalogEntry,
    frame: pd.DataFrame,
    metric: str | None,
    position: str,
) -> BytesIO:
    items = _resolved_legend_items(entry, frame, metric)
    if not items:
        return chart
    chart.seek(0)
    image = Image.open(chart).convert("RGB")
    _draw_chart_legend(
        ImageDraw.Draw(image), items, position,
        line_markers="cdf" in entry.chart_type.casefold(),
        side_x=(1320 if position == "right" and "cdf" in entry.chart_type.casefold() else None),
    )
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def _draw_patterned_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    colour: str,
    width: int,
    dash: tuple[int, ...] = (),
) -> None:
    """Draw one continuous polyline while preserving an optional dash phase."""
    if len(points) < 2:
        return
    if not dash:
        draw.line(points, fill=colour, width=width)
        return
    pattern = tuple(max(float(value), 1.0) for value in dash)
    pattern_index = 0
    remaining = pattern[0]
    drawing = True
    for start, end in zip(points, points[1:]):
        delta_x, delta_y = end[0] - start[0], end[1] - start[1]
        length = math.hypot(delta_x, delta_y)
        if length <= 0:
            continue
        travelled = 0.0
        while travelled < length:
            step = min(remaining, length - travelled)
            first_ratio = travelled / length
            second_ratio = (travelled + step) / length
            first = (start[0] + delta_x * first_ratio, start[1] + delta_y * first_ratio)
            second = (start[0] + delta_x * second_ratio, start[1] + delta_y * second_ratio)
            if drawing:
                draw.line((first, second), fill=colour, width=width)
            travelled += step
            remaining -= step
            if remaining <= 1e-9:
                pattern_index = (pattern_index + 1) % len(pattern)
                remaining = pattern[pattern_index]
                drawing = not drawing


def _horizontal_legend_columns(
    captions: list[str], font_size: int, *, line_markers: bool,
) -> int:
    """Fit complete horizontal legend entries without allowing overlap."""
    if not captions:
        return 1
    font = _font(max(font_size, 17), True)
    marker_width = 43 if line_markers else 32
    longest = max(float(font.getlength(caption[:28])) for caption in captions)
    item_width = max(120.0, marker_width + longest + 24)
    maximum = 6 if line_markers else 5
    return max(1, min(len(captions), maximum, int(1400 // item_width)))


def _group_vendor_legend_items(
    items: list[tuple], frame: pd.DataFrame,
) -> list[tuple]:
    """Group multivendor legend entries by Vendor, then by Operator order."""
    classified: list[tuple[tuple[int, str, int, str, int], tuple, str | None]] = []
    for source_index, item in enumerate(items):
        parts = [part.strip() for part in re.split(r'\s*·\s*', str(item[0])) if part.strip()]
        vendor_group = None
        operator_group = None
        for part in parts:
            vendor_group = vendor_group or _mapping_group(part, 'vendor', frame)
            vendor_group = vendor_group or _mapping_group(_vendor_label(part, frame), 'vendor', frame)
            operator_group = operator_group or _mapping_group(part, 'operator', frame)
            operator_group = operator_group or _mapping_prefix_group(part, 'operator', frame)
        vendor_identity = str(vendor_group.get('canonical')).casefold() if vendor_group else None
        vendor_rank = int(vendor_group.get('position', 0)) if vendor_group else len(_mapping_groups(frame, 'vendor'))
        operator_rank = int(operator_group.get('position', 0)) if operator_group else len(_mapping_groups(frame, 'operator'))
        classified.append(((
            vendor_rank, vendor_identity or '', operator_rank,
            str(operator_group.get('canonical') if operator_group else '').casefold(), source_index,
        ), item, vendor_identity))
    if len({vendor for _key, _item, vendor in classified if vendor is not None}) < 2:
        return items
    return [item for _key, item, _vendor in sorted(classified, key=lambda value: value[0])]


def _draw_chart_legend(
    draw: ImageDraw.ImageDraw,
    items: list[tuple[str, str, int] | tuple[str, str, int, tuple[int, ...]]],
    position: str,
    *,
    font_size: int = 15,
    line_markers: bool = False,
    side_x: int | None = None,
) -> None:
    """Draw a template legend in a row (top/bottom) or column (left/right)."""
    if position == "none" or not items:
        return
    position = parse_legend_position(position)
    # Legends are part of the chart, not ancillary metadata. Enforce a
    # readable minimum because the 1600px PNG is normally scaled down in the
    # report and preview viewers.
    font_size = max(font_size, 17)
    marker_size = 22
    def legend_line_width(series_width: int) -> int:
        # CDF charts are commonly scaled down in previews and PowerPoint. A
        # one-pixel difference (3px vs 4px) is then almost invisible, so
        # exaggerate only the thicker/latest-series sample in the legend.
        return max(series_width + 2 if series_width > 1 else series_width, 3)

    horizontal = position in {"top", "bottom"}
    if horizontal:
        # Dense CDFs can legitimately contain one curve per full hierarchy
        # combination. Reserve six evenly distributed entries per row for
        # line legends (as used by CDF charts), rather than relying on a fixed
        # step that can visually clip the sixth item on narrower renderers.
        columns = _horizontal_legend_columns(
            [str(item[0]) for item in items], font_size, line_markers=line_markers,
        )
        row_height = font_size + 12
        rows = max(1, (len(items) + columns - 1) // columns)
        start_x = 100
        available_width = 1400
        column_width = available_width / columns
        start_y = 80 if position == "top" else 900 - (rows * row_height) - 8
        for index, item in enumerate(items):
            caption, colour, width = item[:3]
            dash = item[3] if len(item) > 3 else ()
            x = start_x + (index % columns) * (column_width if line_markers else 275)
            y = start_y + (index // columns) * row_height
            text_only = not colour
            if line_markers and not text_only:
                _draw_patterned_polyline(
                    draw, [(x, y + 11), (x + 34, y + 11)], colour, legend_line_width(width), dash,
                )
            elif not text_only:
                draw.rectangle((x, y, x + marker_size, y + marker_size), fill=colour)
            draw.text((x if text_only else x + (43 if line_markers else 32), y - 1), caption[:28], fill="#263B4A", font=_font(font_size, True))
        return
    x, start_y = (side_x if side_x is not None else (26 if position == "left" else 1380)), 112
    for index, item in enumerate(items):
        caption, colour, width = item[:3]
        dash = item[3] if len(item) > 3 else ()
        y = start_y + index * (font_size + 14)
        text_only = not colour
        if line_markers and not text_only:
            _draw_patterned_polyline(
                draw, [(x, y + 11), (x + 34, y + 11)], colour, legend_line_width(width), dash,
            )
        elif not text_only:
            draw.rectangle((x, y, x + marker_size, y + marker_size), fill=colour)
        draw.text((x if text_only else x + (43 if line_markers else 32), y - 1), caption[:24], fill="#263B4A", font=_font(font_size, True))


def _catalogue_display_label(category: object, series: object) -> str:
    """Keep row categories visible while using column groups as comparisons."""
    category_text, series_text = str(category), str(series)
    return category_text if series_text == "(all)" else f"{category_text} · {series_text}"


def _hierarchical_unique_keys(frame: pd.DataFrame, columns: list[str]) -> list[tuple[object, ...]]:
    """Keep every child grouping value adjacent to its parent.

    Source CDRs are commonly appended campaign by campaign.  Their natural row
    order can therefore be ``Vodafone/2025, O2/2025, Vodafone/2026, O2/2026``.
    That order would split the visible Vodafone group into two separate chart
    sections.  Retain the first-seen order of each level, but traverse the
    hierarchy depth-first so all campaign bars for one operator stay together.
    """
    keys = list(frame[columns].drop_duplicates().itertuples(index=False, name=None))
    if len(columns) < 2:
        return keys

    ordered: list[tuple[object, ...]] = []

    def visit(values: list[tuple[object, ...]], level: int) -> None:
        if level == len(columns) - 1:
            ordered.extend(values)
            return
        groups: dict[object, list[tuple[object, ...]]] = {}
        for key in values:
            groups.setdefault(key[level], []).append(key)
        for children in groups.values():
            visit(children, level + 1)

    visit(keys, 0)
    return ordered


def _hierarchical_complete_keys(frame: pd.DataFrame, columns: list[str]) -> list[tuple[object, ...]]:
    """Return a complete hierarchy grid without inventing cross-parent children.

    Explicit values still complete the leaf level (for example every Campaign
    for a Vendor), while observed parent-child relationships keep vendors under
    their own Operator instead of producing empty combinations for every pair.
    """
    if not columns:
        return [()]
    configured_values = frame.attrs.get("catalogue_dimension_values", {})
    labels = frame.attrs.get("catalogue_dimension_labels", {})
    observed = list(frame[columns].drop_duplicates().itertuples(index=False, name=None))
    if not observed:
        return []
    keys: list[tuple[object, ...]] = []

    def children(prefix: tuple[object, ...], level: int) -> list[object]:
        matching = [key[level] for key in observed if key[:level] == prefix]
        observed_values = list(dict.fromkeys(matching))
        configured = list(configured_values.get(columns[level]) or ())
        # A configured terminal dimension represents expected comparison slots
        # (normally Campaign). Parent levels must remain tied to their source
        # branch so Operator/Vendor nesting is always truthful.
        if level == len(columns) - 1 and configured:
            return configured
        return observed_values or configured

    def visit(prefix: tuple[object, ...], level: int) -> None:
        for value in children(prefix, level):
            key = (*prefix, value)
            if level == len(columns) - 1:
                keys.append(key)
            else:
                visit(key, level + 1)

    visit((), 0)
    return keys


def _hierarchy_caption_spans(
    keys: list[tuple[object, ...]], level: int,
) -> list[tuple[int, int, str]]:
    """Return adjacent hierarchy groups for one visible header level."""
    if not keys or level < 0 or level >= len(keys[0]):
        return []
    spans: list[tuple[int, int, str]] = []
    start = 0
    while start < len(keys):
        end = start + 1
        prefix = keys[start][:level + 1]
        while end < len(keys) and keys[end][:level + 1] == prefix:
            end += 1
        spans.append((start, end, str(keys[start][level])))
        start = end
    return spans


def _fit_text(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.ImageFont, width: float) -> str:
    """Trim a caption with an ellipsis so it stays inside its hierarchy group."""
    if _text_width(draw, value, font) <= width:
        return value
    suffix = "…"
    available = max(width - _text_width(draw, suffix, font), 0)
    fitted = ""
    for character in value:
        if _text_width(draw, fitted + character, font) > available:
            break
        fitted += character
    return fitted.rstrip() + suffix if fitted else suffix


def _canvas(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 20), title, fill="#1D3345", font=_font(40, True))
    return image, draw


def _text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.ImageFont) -> int:
    """Return the rendered width of a label, including the actual font metrics."""
    return int(draw.textbbox((0, 0), value, font=font)[2])


def _draw_rotated_label(
    image: Image.Image,
    value: str,
    *,
    centre_x: float,
    bottom_y: float,
    fill: str,
    font: ImageFont.ImageFont,
    angle: int = 45,
) -> None:
    """Draw a rotated label centred on ``centre_x`` with its bottom at ``bottom_y``.

    Axis captions are deliberately rotated only when their measured text no
    longer fits the space assigned to a group.  Rendering to a transparent
    layer avoids clipping the anti-aliased glyphs on the white chart canvas.
    """
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), value, font=font)
    label = Image.new("RGBA", (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4 - bbox[0], 4 - bbox[1]), value, fill=fill, font=font)
    rotated = label.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(rotated, (round(centre_x - rotated.width / 2), round(bottom_y - rotated.height)), rotated)


def _draw_vertical_label(
    image: Image.Image,
    value: str,
    *,
    centre_x: float,
    centre_y: float,
    fill: str,
    font: ImageFont.ImageFont,
) -> None:
    """Draw a y-axis caption centred vertically and rotated by 90 degrees."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), value, font=font)
    label = Image.new("RGBA", (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(label).text((4 - bbox[0], 4 - bbox[1]), value, fill=fill, font=font)
    rotated = label.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(rotated, (round(centre_x - rotated.width / 2), round(centre_y - rotated.height / 2)), rotated)


def _draw_inside_bar_label(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: str,
    font: ImageFont.ImageFont,
) -> bool:
    """Draw a bar value horizontally or vertically when the latter fits better."""
    label_width = _text_width(draw, value, font)
    label_box = draw.textbbox((0, 0), value, font=font)
    label_height = label_box[3] - label_box[1]
    if label_width + 8 <= width and label_height + 8 <= height:
        draw.text((x + (width - label_width) / 2, y + (height - label_height) / 2 - label_box[1]), value, fill=fill, font=font)
        return True
    if label_height + 8 <= width and label_width + 8 <= height:
        _draw_vertical_label(image, value, centre_x=x + width / 2, centre_y=y + height / 2, fill=fill, font=font)
        return True
    return False


def _draw_adjacent_stacked_bar_label(
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    bar_top: float,
    bar_bottom: float,
    fill: str,
    font: ImageFont.ImageFont,
) -> bool:
    """Place a tiny segment label inside its bar, adjacent to that segment."""
    box = draw.textbbox((0, 0), value, font=font)
    label_width, label_height = box[2] - box[0], box[3] - box[1]
    if label_width + 8 > width:
        return False
    below = y + height + 3
    above = y - label_height - 5
    label_y = below if below + label_height + 4 <= bar_bottom else above if above >= bar_top else None
    if label_y is None:
        return False
    draw.text(
        (x + (width - label_width) / 2, label_y - box[1]),
        value, fill=fill, font=font,
    )
    return True


def _draw_configured_bar_label(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    value: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    colour: str,
    font: ImageFont.ImageFont,
    position: str,
    horizontal: bool,
    automatic: Callable[[], None],
) -> None:
    """Draw an explicit template label placement or retain legacy behaviour."""
    placement = position.casefold()
    if not placement:
        automatic()
        return
    if placement == "none":
        return
    box = draw.textbbox((0, 0), value, font=font)
    label_width, label_height = box[2] - box[0], box[3] - box[1]
    if placement == "top":
        point = (
            (x + width + 5, y + (height - label_height) / 2 - box[1])
            if horizontal else (x + (width - label_width) / 2, y - label_height - 4 - box[1])
        )
        draw.text(point, value, fill=colour, font=font)
        return
    if horizontal:
        label_x = x + width - label_width - 4 if placement == "up" else (x + 4 if placement == "down" else x + (width - label_width) / 2)
        label_y = y + (height - label_height) / 2 - box[1]
    else:
        if label_width + 8 > width and label_height + 8 <= width and label_width + 8 <= height:
            centre_y = (
                y + label_width / 2 + 4 if placement == "up"
                else y + height - label_width / 2 - 4 if placement == "down"
                else y + height / 2
            )
            _draw_vertical_label(
                image, value, centre_x=x + width / 2, centre_y=centre_y,
                fill="#FFFFFF", font=font,
            )
            return
        label_x = x + (width - label_width) / 2
        label_y = y + 4 - box[1] if placement == "up" else (y + height - label_height - 4 - box[1] if placement == "down" else y + (height - label_height) / 2 - box[1])
    draw.text((label_x, label_y), value, fill="#FFFFFF", font=font)


def _draw_dashed_vertical_line(
    draw: ImageDraw.ImageDraw,
    x: float,
    top: float,
    bottom: float,
    *,
    fill: str = "#AEBBC4",
    dash: int = 8,
    gap: int = 6,
) -> None:
    """Draw a light vertical group separator without obscuring bar values."""
    y = top
    while y < bottom:
        draw.line((x, y, x, min(y + dash, bottom)), fill=fill, width=1)
        y += dash + gap


def _draw_dashed_horizontal_line(
    draw: ImageDraw.ImageDraw,
    y: float,
    left: float,
    right: float,
    *,
    fill: str = "#AEBBC4",
    dash: int = 8,
    gap: int = 6,
) -> None:
    """Draw a light horizontal separator between child row values."""
    x = left
    while x < right:
        draw.line((x, y, min(x + dash, right), y), fill=fill, width=1)
        x += dash + gap


def _draw_top_column_group_separators(
    draw: ImageDraw.ImageDraw,
    keys: list[tuple[object, ...]],
    axis_columns: list[str],
    *,
    left: float,
    width: float,
    top: float,
    bottom: float,
) -> None:
    """Draw solid outer and dashed nested boundaries for bar hierarchies.

    Every declared x-axis dimension is visible in the nested header, including
    row aggregation fields. A change in its first level starts a continuous
    outer boundary. Child changes use a dashed line that starts below the
    corresponding parent header, preserving the grouping structure.
    """
    if len(keys) < 2:
        return
    header_top = top - 30 * (len(keys[0]) if keys else 1) - 8
    for index in range(1, len(keys)):
        previous, current = keys[index - 1], keys[index]
        changed = next((level for level, value in enumerate(current) if value != previous[level]), None)
        if changed is None:
            continue
        x = left + index * width / len(keys)
        if changed == 0:
            draw.line((x, header_top, x, bottom), fill="#AEBBC4", width=2)
        else:
            _draw_dashed_vertical_line(draw, x, header_top + changed * 30, bottom)


def _empty_chart(title: str) -> BytesIO:
    image, draw = _canvas(title)
    draw.text((50, 440), "No valid samples for this KPI and technology filter", fill="#61727D", font=_font(24))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _status_chart_categories(
    data: pd.DataFrame, state_column: str, *, quality: bool, threshold: float,
    copy: bool = True,
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    """Classify every non-empty result so 100% bars have no unpainted remainder."""
    result = data.copy() if copy else data
    if quality:
        numeric = pd.to_numeric(result[state_column], errors="coerce")
        result = result.loc[numeric.notna()].copy()
        result["state"] = numeric.loc[result.index].map(lambda value: "< 1.6" if value < threshold else "≥ 1.6")
        return result, ("< 1.6", "≥ 1.6"), ("#C83E4D", "#2C9A62")
    canonical_labels = {
        "completed": "Completed", "drop": "Dropped", "dropped": "Dropped", "failed": "Failed", "cutoff": "Cutoff",
    }
    # Status columns contain only a handful of distinct labels even when a
    # chart has hundreds of thousands of rows. Normalise and classify every
    # distinct source value once, then use pandas' vectorised hash mapping.
    state_by_value: dict[object, str | None] = {}
    for value in result[state_column].dropna().drop_duplicates():
        label = str(value).strip()
        canonical = canonical_labels.get(label.casefold())
        state_by_value[value] = canonical or (label if _outcome_kind(label) is not None else None)
    semantic = result[state_column].map(state_by_value)
    # Status KPIs intentionally ignore unknown outcomes. Other categorical
    # KPIs (RAT, CA state, ARFCN, threshold buckets) retain their native values.
    result["state"] = (
        semantic if semantic.notna().any() else result[state_column].map(
            {value: str(value).strip() for value in result[state_column].dropna().drop_duplicates()}
        )
    ).replace({"": pd.NA, "<NA>": pd.NA, "NaN": pd.NA, "nan": pd.NA})
    present = [str(value) for value in result["state"].dropna().drop_duplicates()]
    preferred = [state for state in ("Completed", "Success", "Cutoff", "Dropped", "Failed", "Failure") if state in present]
    states = tuple([*preferred, *sorted((state for state in present if state not in preferred), key=str.casefold)])
    offsets = {"success": 0, "failure": 0}
    neutral_index = 0
    colours_list: list[str] = []
    for state in states:
        kind = _outcome_kind(state)
        if kind:
            variants = OUTCOME_COLOUR_VARIANTS[kind]
            colours_list.append(variants[offsets[kind] % len(variants)])
            offsets[kind] += 1
        else:
            colours_list.append(_colour(state, neutral_index))
            neutral_index += 1
    colours = tuple(colours_list)
    return result, states, colours


def _render_status_100(title: str, frame: pd.DataFrame, group: str | None, period: str | None, quality: bool = False, threshold: float = 1.6, metric: str | None = None, legend_labels: tuple[str, ...] = (), legend_position: str = "top", label_position: str = "") -> BytesIO:
    if frame.empty or not group or not period:
        return _empty_chart(title)
    image, draw = _canvas(title)
    # Honour the template/Interactive Preview KPI for status charts too. The
    # former fallback could silently pick Call_Status from a processed frame
    # even when the selected KPI was Test_Result.
    state_column = metric or _column(frame, ("Call_Status", "Test_Result", "status"))
    if not state_column:
        return _empty_chart(title)
    hierarchy_columns = sorted(
        [column for column in frame.columns if column.startswith("__catalog_row_") or column.startswith("__catalog_column_")],
        key=lambda column: (0 if column.startswith("__catalog_row_") else 1, int(column.rsplit("_", 1)[1])),
    )
    data = frame[[group, period, state_column, *hierarchy_columns]].copy()
    data, states, colours = _status_chart_categories(data, state_column, quality=quality, threshold=threshold)
    data = data.dropna(subset=[group, period])
    row_hierarchy = [column for column in hierarchy_columns if column.startswith("__catalog_row_")]
    column_hierarchy = [column for column in hierarchy_columns if column.startswith("__catalog_column_")]
    if column_hierarchy:
        return _render_status_100_hierarchy(title, data, row_hierarchy, column_hierarchy, states, colours, legend_labels, legend_position, label_position)
    if row_hierarchy:
        # A row-only hierarchy remains on the left. A synthetic single column
        # gives every row its own bar without moving row dimensions to the x axis.
        single_column = "__catalog_single_column"
        data[single_column] = "(all)"
        return _render_status_100_hierarchy(
            title, data, row_hierarchy, [single_column], states, colours,
            legend_labels, legend_position, label_position,
        )
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
            value_label = f"{value:.1%}"
            def automatic_label() -> None:
                if value >= .08 and _draw_inside_bar_label(image, draw, value_label, x=x, y=y, width=bar_width, height=height, fill="white", font=_font(20, True)):
                    return
                if value >= .005:
                    _draw_adjacent_stacked_bar_label(
                        draw, value_label, x=x, y=y, width=bar_width, height=height,
                        bar_top=chart_top, bar_bottom=chart_top + chart_height,
                        fill=colour, font=_font(14, True),
                    )
            _draw_configured_bar_label(image, draw, value_label, x=x, y=y, width=bar_width, height=height, colour=colour, font=_font(20, True), position=label_position, horizontal=False, automatic=automatic_label)
            running += height
        label = _catalogue_display_label(g, p)[:24]
        label_font = _font(18, True)
        if _text_width(draw, label, label_font) > chart_width / len(combos) - 8:
            _draw_rotated_label(image, label, centre_x=x + bar_width / 2, bottom_y=chart_top + chart_height + 75, fill="#5A6B78", font=label_font)
        else:
            draw.text((x - 4, chart_top + chart_height + 8), label, fill="#5A6B78", font=label_font)
    for y in range(0, 101, 20):
        value_y = chart_top + chart_height - (y / 100 * chart_height)
        draw.line((chart_left - 20, value_y, chart_left + chart_width, value_y), fill="#E4E9ED", width=1)
        draw.text((64, value_y - 10), f"{y}%", fill="#4E6271", font=_font(18, True))
    _draw_chart_legend(draw, [(_legend_caption(legend_labels, index, state), colour, 2) for index, (state, colour) in enumerate(zip(states, colours, strict=True))], legend_position, font_size=16)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_status_100_hierarchy(
    title: str,
    data: pd.DataFrame,
    row_hierarchy: list[str],
    column_hierarchy: list[str],
    states: tuple[str, ...],
    colours: tuple[str, ...],
    legend_labels: tuple[str, ...] = (),
    legend_position: str = "top",
    label_position: str = "",
) -> BytesIO:
    """Render template row groups as panes and column groups as nested headers."""
    row_keys = _hierarchical_unique_keys(data, row_hierarchy) if row_hierarchy else [()]
    column_keys = _hierarchical_unique_keys(data, column_hierarchy)
    if not row_keys or not column_keys:
        return _empty_chart(title)

    image, draw = _canvas(title)
    # Reserve a dedicated header band below the chart title.  Rotated vendor /
    # operator captions can be tall, so they must never share the title area.
    row_label_font = _font(18, True)
    row_label_widths = [
        max((_text_width(draw, str(key[level])[:24], row_label_font) for key in row_keys), default=0) + 18
        for level in range(len(row_hierarchy))
    ]
    # Leave a measured gutter for row labels, percentage ticks and a visual
    # gap before the plot.  Fixed gutters caused long FDFS/test-family labels
    # to cross the y axis on multi-pane charts.
    available_row_width = min(sum(row_label_widths), 420)
    chart_left = max(145, min(540, 24 + available_row_width + 68))
    # Bottom legends occupy the same lower canvas band as rotated leaf labels.
    # Reserve that band before plotting so column captions never overlap the
    # legend, regardless of the number of hierarchy levels.
    bottom_legend_reserve = 122 if parse_legend_position(legend_position) == "bottom" and legend_labels else 0
    chart_top, chart_right, chart_height = 245, 1395, 510 - bottom_legend_reserve
    chart_width = chart_right - chart_left
    row_height = chart_height / len(row_keys)
    column_width = chart_width / len(column_keys)
    bar_width = max(18, min(86, column_width * 0.68))

    # Every column dimension except the leaf gets its own nested band above the
    # plot. Only the final dimension is repeated below individual bars.
    upper_levels = max(len(column_hierarchy) - 1, 0)
    header_band_height = min(32.0, 112.0 / max(upper_levels, 1))
    header_top = chart_top - upper_levels * header_band_height - 8
    total_label_width = max(sum(row_label_widths), 1)
    row_label_scale = min((chart_left - 92) / total_label_width, 1.0)
    def nested_row_start(level: int) -> float:
        return 24 + sum(row_label_widths[:level]) * row_label_scale
    header_font = _font(15, True)
    for level in range(upper_levels):
        band_top = header_top + level * header_band_height
        for start, end, value in _hierarchy_caption_spans(column_keys, level):
            left = chart_left + start * column_width
            right = chart_left + end * column_width
            caption = _fit_text(draw, value, header_font, right - left - 10)
            caption_width = _text_width(draw, caption, header_font)
            draw.text((left + (right - left - caption_width) / 2, band_top + 2), caption, fill="#405765", font=header_font)
            draw.line((left, band_top + header_band_height - 3, right, band_top + header_band_height - 3), fill="#BCC8D0", width=1)

    for index in range(1, len(column_keys)):
        changed_level = next(
            (level for level, (previous, current) in enumerate(zip(column_keys[index - 1], column_keys[index], strict=True)) if previous != current),
            len(column_hierarchy) - 1,
        )
        x = chart_left + index * column_width
        line_top = header_top + min(changed_level, upper_levels) * header_band_height
        if changed_level == 0:
            draw.line((x, line_top, x, chart_top + chart_height), fill="#AEBBC4", width=2)
        else:
            _draw_dashed_vertical_line(draw, x, line_top, chart_top + chart_height)

    for row_index, row_key in enumerate(row_keys):
        pane_top = chart_top + row_index * row_height
        pane_bottom = pane_top + row_height
        next_row_key = row_keys[row_index + 1] if row_index + 1 < len(row_keys) else None
        changed_level = next((level for level, value in enumerate(row_key) if next_row_key is not None and value != next_row_key[level]), 0)
        if next_row_key is None or changed_level == 0:
            draw.line((24, pane_bottom, chart_left + chart_width, pane_bottom), fill="#AEBBC4", width=2)
        else:
            _draw_dashed_horizontal_line(draw, pane_bottom, nested_row_start(changed_level), chart_left + chart_width)
        ticks = (0, 50, 100) if row_index == len(row_keys) - 1 else (50, 100)
        for tick in ticks:
            tick_y = pane_bottom - tick / 100 * row_height
            draw.line((chart_left, tick_y, chart_left + chart_width, tick_y), fill="#E8ECEF", width=1)
            draw.text((chart_left - 50, tick_y - 9), f"{tick}%", fill="#566A78", font=_font(15, True))

        row_mask = pd.Series(True, index=data.index)
        for field, value in zip(row_hierarchy, row_key, strict=True):
            row_mask &= data[field].astype(str).eq(str(value))
        for column_index, column_key in enumerate(column_keys):
            mask = row_mask.copy()
            for field, value in zip(column_hierarchy, column_key, strict=True):
                mask &= data[field].astype(str).eq(str(value))
            subset = data.loc[mask]
            if subset.empty:
                # A grouping grid intentionally retains every column so its
                # headers remain comparable between rows.  Mark absent source
                # combinations explicitly instead of leaving misleading blank
                # space (for example, a vendor with no MultiRAB samples).
                centre_x = chart_left + (column_index + .5) * column_width
                draw.text((centre_x - 5, pane_top + row_height / 2 - 7), "—", fill="#B5C0C8", font=_font(14))
                continue
            x = chart_left + column_index * column_width + (column_width - bar_width) / 2
            total = len(subset)
            running = 0.0
            for state, colour in zip(states, colours, strict=True):
                ratio = float(subset["state"].eq(state).sum()) / total
                segment_height = ratio * row_height
                y = pane_bottom - running - segment_height
                draw.rectangle((x, y, x + bar_width, y + segment_height), fill=colour)
                ratio_label = f"{ratio:.1%}"
                def automatic_label() -> None:
                    if ratio >= 0.08 and _draw_inside_bar_label(image, draw, ratio_label, x=x, y=y, width=bar_width, height=segment_height, fill="white", font=_font(21, True)):
                        return
                    if ratio >= 0.005:
                        _draw_adjacent_stacked_bar_label(
                            draw, ratio_label, x=x, y=y, width=bar_width, height=segment_height,
                            bar_top=pane_top, bar_bottom=pane_bottom,
                            fill=colour, font=_font(14, True),
                        )
                _draw_configured_bar_label(image, draw, ratio_label, x=x, y=y, width=bar_width, height=segment_height, colour=colour, font=_font(21, True), position=label_position, horizontal=False, automatic=automatic_label)
                running += segment_height

    if row_hierarchy:
        scale = row_label_scale
        x = 24.0
        for level, width in enumerate(row_label_widths):
            visible_width = width * scale
            for start, end, value in _hierarchy_caption_spans(row_keys, level):
                centre_y = chart_top + ((start + end) / 2) * row_height
                caption = _fit_text(draw, value, row_label_font, visible_width - 8)
                draw.text((x + 4, centre_y - 10), caption, fill="#405765", font=row_label_font)
            x += visible_width
            draw.line((x, chart_top, x, chart_top + chart_height), fill="#D7DEE3", width=1)

    hide_single_column = column_hierarchy == ["__catalog_single_column"]
    lower_captions = ["" if hide_single_column else str(key[-1]) for key in column_keys]
    lower_font = _font(16, True)
    rotate_axis_captions = any(
        _text_width(draw, caption, lower_font) + 8 > column_width
        for caption in lower_captions
    )
    for column_index, lower_caption in enumerate(lower_captions):
        if not lower_caption:
            continue
        centre = chart_left + (column_index + 0.5) * column_width
        if rotate_axis_captions:
            _draw_rotated_label(image, lower_caption[:24], centre_x=centre, bottom_y=chart_top + chart_height + 90, fill="#4E6271", font=lower_font)
        else:
            caption = _fit_text(draw, lower_caption, lower_font, column_width - 8)
            draw.text((centre - _text_width(draw, caption, lower_font) / 2, chart_top + chart_height + 10), caption, fill="#4E6271", font=lower_font)

    _draw_chart_legend(draw, [(_legend_caption(legend_labels, index, state), colour, 2) for index, (state, colour) in enumerate(zip(states, colours, strict=True))], legend_position)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _render_failure_count(title: str, frame: pd.DataFrame, group: str | None, period: str | None, legend_labels: tuple[str, ...] = (), legend_position: str = "top", label_position: str = "") -> BytesIO:
    if frame.empty or not group:
        return _empty_chart(title)
    status = _column(frame, ("Call_Status", "Test_Result", "status"))
    if not status: return _empty_chart(title)
    failed = frame[frame[status].astype(str).str.contains("failed|drop|cutoff", case=False, na=False)].copy()
    failed["__catalog_failure_state"] = failed[status].astype(str).map(
        lambda value: "Dropped" if "drop" in value.casefold() else "Failed"
    )
    row_hierarchy = sorted(
        [column for column in frame.columns if column.startswith("__catalog_row_")],
        key=lambda column: int(column.rsplit("_", 1)[1]),
    )
    column_hierarchy = sorted(
        [column for column in frame.columns if column.startswith("__catalog_column_")],
        key=lambda column: int(column.rsplit("_", 1)[1]),
    )
    if column_hierarchy:
        return _render_failure_count_hierarchy(
            title, failed, row_hierarchy, column_hierarchy, legend_labels, legend_position, label_position, comparison_frame=frame,
        )
    if len(row_hierarchy) > 1:
        return _render_failure_count_hierarchy(title, failed, [], row_hierarchy, legend_labels, legend_position, label_position, comparison_frame=frame)
    has_series = bool(period) and not frame[period].fillna("(all)").astype(str).eq("(all)").all()
    fields = [group, period] if has_series else [group]
    counts = failed.groupby([*fields, "__catalog_failure_state"], dropna=False).size().unstack(fill_value=0)
    comparison_keys = _hierarchical_complete_keys(frame, fields)
    if len(fields) == 1:
        comparison_index = pd.Index([key[0] for key in comparison_keys], name=fields[0])
    else:
        comparison_index = pd.MultiIndex.from_tuples(comparison_keys, names=fields)
    counts = counts.reindex(comparison_index, fill_value=0)
    counts = counts.head(16)
    image, draw = _canvas(title); maximum = max(int(counts.sum(axis=1).max()), 1)
    colours = {"Failed": "#C83E4D", "Dropped": "#D8555F"}
    for index, (labels, values) in enumerate(counts.iterrows()):
        labels = labels if isinstance(labels, tuple) else (labels,)
        y = 120 + index * 42; x = 390
        draw.text((28, y + 4), " · ".join(str(value) for value in labels)[:42], fill="#263B4A", font=_font(17, True))
        for state in ("Failed", "Dropped"):
            count = int(values.get(state, 0)); width = int(980 * count / maximum)
            if width:
                draw.rectangle((x, y, x + width, y + 30), fill=colours[state])
                _draw_configured_bar_label(image, draw, str(count), x=x, y=y, width=width, height=30, colour=colours[state], font=_font(20, True), position=label_position, horizontal=True, automatic=lambda: _draw_inside_bar_label(image, draw, str(count), x=x, y=y, width=width, height=30, fill="white", font=_font(20, True)))
            x += width
    _draw_chart_legend(draw, [(_legend_caption(legend_labels, index, state), colours[state], 2) for index, state in enumerate(("Failed", "Dropped"))], legend_position, font_size=13)
    draw.text((390, 820), "# of failed / dropped sessions", fill="#4E6271", font=_font(19, True))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_failure_count_hierarchy(
    title: str,
    failed: pd.DataFrame,
    row_hierarchy: list[str],
    column_hierarchy: list[str],
    legend_labels: tuple[str, ...] = (),
    legend_position: str = "top",
    label_position: str = "",
    comparison_frame: pd.DataFrame | None = None,
) -> BytesIO:
    """Render failure counts with template rows and columns as separate axes."""
    comparison = comparison_frame if comparison_frame is not None else failed
    # Keep the complete aggregation grids even when a combination has no
    # failure rows. This makes zero-count horizontal bars explicit rather than
    # silently removing a row/column from the comparison.
    row_keys = _hierarchical_complete_keys(comparison, row_hierarchy) if row_hierarchy else [()]
    column_keys = _hierarchical_complete_keys(comparison, column_hierarchy)
    if not row_keys or not column_keys:
        return _empty_chart(title)

    counts = failed.groupby([*row_hierarchy, *column_hierarchy, "__catalog_failure_state"], dropna=False).size()
    if counts.empty:
        maximum = 1
    else:
        maximum = max(int(counts.groupby(level=list(range(len(row_hierarchy) + len(column_hierarchy)))).sum().max()), 1)
    image, draw = _canvas(title)
    # See the status renderer above: hierarchy captions use the space between
    # the title and the plot, not the title itself.
    chart_left, chart_top, chart_height = 285, 245, 510
    # A right-side legend needs its own canvas lane. Without reserving it, the
    # diagonal outer column captions extend into the legend area on dense
    # hierarchy charts (for example Operator × Campaign failure matrices).
    chart_width = 980 if legend_position == "right" else 1250
    upper_levels = max(len(column_keys[0]) - 1, 0)
    header_band_height = min(34, 120 / upper_levels) if upper_levels else 0
    header_top = chart_top - upper_levels * header_band_height - 8
    leaf_label_y = chart_top - 10
    row_height = chart_height / len(row_keys)
    column_width = chart_width / len(column_keys)
    colours = {"Failed": "#C83E4D", "Dropped": "#D8555F"}
    for level in range(upper_levels):
        y = header_top + level * header_band_height
        for start, end, caption in _hierarchy_caption_spans(column_keys, level):
            centre = chart_left + ((start + end) / 2) * column_width
            caption = caption[:20]
            font = _font(17, True)
            draw.text((centre - min(_text_width(draw, caption, font) / 2, (end - start) * column_width / 2 - 4), y), caption, fill="#566A78", font=font)
            draw.line((chart_left + start * column_width, y + header_band_height - 4, chart_left + end * column_width, y + header_band_height - 4), fill="#C8D2D9", width=1)

    for column_index, column_key in enumerate(column_keys):
        lower_caption = str(column_key[-1])
        centre = chart_left + (column_index + 0.5) * column_width
        draw.text((centre - min(len(lower_caption) * 4, 68), leaf_label_y), lower_caption[:18], fill="#4E6271", font=_font(15, True))
        cell_left = chart_left + column_index * column_width
        if column_index:
            changed = next((level for level, value in enumerate(column_key) if value != column_keys[column_index - 1][level]), len(column_key) - 1)
            line_top = header_top if changed == 0 else header_top + min(changed, upper_levels) * header_band_height
            if changed == 0:
                draw.line((cell_left, line_top, cell_left, chart_top + chart_height + 25), fill="#AEBBC4", width=2)
            else:
                _draw_dashed_vertical_line(draw, cell_left, line_top, chart_top + chart_height + 25)
        else:
            draw.line((cell_left, header_top, cell_left, chart_top + chart_height + 25), fill="#AEBBC4", width=2)
        draw.text((cell_left + 3, chart_top + chart_height + 7), "0", fill="#566A78", font=_font(13, True))
        draw.text((cell_left + column_width - 25, chart_top + chart_height + 7), str(maximum), fill="#566A78", font=_font(13, True))

    # Render each row hierarchy level in its own label column. Repeated outer
    # values are merged visually so Call Family remains distinct from G Level 4.
    label_width = max((chart_left - 28) / len(row_hierarchy), 65) if row_hierarchy else 0
    for level, field in enumerate(row_hierarchy):
        values = [str(key[level]) for key in row_keys]
        start = 0
        while start < len(row_keys):
            end = start + 1
            while end < len(row_keys) and row_keys[end][:level + 1] == row_keys[start][:level + 1]:
                end += 1
            centre_y = chart_top + ((start + end) / 2) * row_height
            x = 20 + level * label_width
            draw.text((x, centre_y - 9), values[start][:22], fill="#405765", font=_font(14, True))
            start = end

    for row_index, row_key in enumerate(row_keys):
        row_top = chart_top + row_index * row_height
        row_bottom = row_top + row_height
        next_row_key = row_keys[row_index + 1] if row_index + 1 < len(row_keys) else None
        changed_level = next((level for level, value in enumerate(row_key) if next_row_key is not None and value != next_row_key[level]), 0)
        if next_row_key is not None and changed_level > 0:
            # Nested row separators start below their parent label column.
            _draw_dashed_horizontal_line(draw, row_bottom, 20 + label_width * changed_level, chart_left + chart_width)
        else:
            draw.line((20, row_bottom, chart_left + chart_width, row_bottom), fill="#AEBBC4", width=2)
        for column_index, column_key in enumerate(column_keys):
            key_prefix = (*row_key, *column_key)
            state_counts = {
                state: int(counts.get((*key_prefix, state), 0))
                for state in ("Failed", "Dropped")
            }
            cell_left = chart_left + column_index * column_width
            available_width = max(column_width - 10, 1)
            x = cell_left + 4
            # Dense failure charts can contain dozens of city rows.  Reserve
            # enough height for a real count label rather than rendering a
            # clipped white glyph against the bar edge.
            bar_height = max(16, min(26, row_height * 0.84))
            y = row_top + (row_height - bar_height) / 2
            count_font = _font(16, True)
            outside_counts: list[str] = []
            for state in ("Failed", "Dropped"):
                count = state_counts[state]
                segment_width = available_width * count / maximum
                if segment_width:
                    draw.rectangle((x, y, x + segment_width, y + bar_height), fill=colours[state])
                    label = str(count)
                    label_width = _text_width(draw, label, count_font)
                    def automatic_label() -> None:
                        if not _draw_inside_bar_label(image, draw, label, x=x, y=y, width=segment_width, height=bar_height, fill="white", font=count_font):
                            outside_counts.append(label)
                    _draw_configured_bar_label(image, draw, label, x=x, y=y, width=segment_width, height=bar_height, colour=colours[state], font=count_font, position=label_position, horizontal=True, automatic=automatic_label)
                x += segment_width
            if outside_counts:
                # Keep labels visible even when an individual stacked segment
                # is too narrow. The ordered values still follow Failed,
                # Dropped as documented by the legend.
                draw.text((x + 3, y + 1), " / ".join(outside_counts), fill="#34495A", font=count_font)

    draw.line((chart_left + chart_width, header_top, chart_left + chart_width, chart_top + chart_height + 25), fill="#AEBBC4", width=2)
    _draw_chart_legend(
        draw,
        [(_legend_caption(legend_labels, index, state), colours[state], 2) for index, state in enumerate(("Failed", "Dropped"))],
        legend_position,
        font_size=13,
        side_x=int(chart_left + chart_width + 24) if legend_position == "right" else None,
    )
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _chart_axis_hierarchy(frame: pd.DataFrame, *, distribution: bool = False) -> list[str]:
    """Return visible template hierarchy levels in their declared order."""
    rows = sorted(
        (column for column in frame.columns if column.startswith("__catalog_row_")),
        key=lambda column: int(column.rsplit("_", 1)[1]),
    )
    columns = sorted(
        (column for column in frame.columns if column.startswith("__catalog_column_")),
        key=lambda column: int(column.rsplit("_", 1)[1]),
    )
    # Distribution charts use their final column level as the stack, never as
    # an x-axis category.
    return [*rows, *(columns[:-1] if distribution and columns else columns)]


def _hierarchy_spans(keys: list[tuple[object, ...]], level: int) -> list[tuple[int, int]]:
    """Return contiguous spans sharing the same hierarchy prefix at *level*."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(keys):
        end = start + 1
        while end < len(keys) and keys[end][:level + 1] == keys[start][:level + 1]:
            end += 1
        spans.append((start, end))
        start = end
    return spans


def _draw_hierarchical_axis_labels(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    keys: list[tuple[object, ...]],
    left: float,
    width: float,
    top: float,
    bottom: float,
) -> None:
    """Draw hierarchy captions using the least rotation each label needs."""
    if not keys:
        return
    levels = len(keys[0])
    item_width = width / len(keys)

    def label_angle(value: str, available_width: float, font: ImageFont.ImageFont) -> int:
        measured = _text_width(draw, value, font)
        if measured + 8 <= available_width:
            return 0
        # At 45° both the text width and height consume horizontal space. A
        # vertical caption is reserved for labels that still cannot fit there.
        height = draw.textbbox((0, 0), value, font=font)[3]
        return 45 if (measured + height) * math.sqrt(0.5) + 8 <= available_width else 90

    for level in range(max(levels - 1, 0)):
        for start, end in _hierarchy_spans(keys, level):
            centre = left + ((start + end) / 2) * item_width
            text = str(keys[start][level])[:20]
            y = top - 30 * (levels - level)
            font = _font(18, True)
            angle = label_angle(text, (end - start) * item_width, font)
            if angle:
                _draw_rotated_label(image, text, centre_x=centre, bottom_y=y + 24, fill="#566A78", font=font, angle=angle)
            else:
                text_width = _text_width(draw, text, font)
                draw.text((centre - text_width / 2, y), text, fill="#566A78", font=font)
            draw.line((left + start * item_width, y + 24, left + end * item_width, y + 24), fill="#CDD7DE", width=1)
    for index, key in enumerate(keys):
        text = str(key[-1])[:18]
        centre = left + (index + .5) * item_width
        font = _font(16, True)
        angle = label_angle(text, item_width, font)
        if angle:
            _draw_rotated_label(image, text, centre_x=centre, bottom_y=bottom + (78 if angle == 45 else 106), fill="#62727E", font=font, angle=angle)
        else:
            text_width = _text_width(draw, text, font)
            draw.text((centre - text_width / 2, bottom + 11), text, fill="#62727E", font=font)


def _render_stacked_distribution(title: str, frame: pd.DataFrame, group: str | None, series: str | None, stack: str, legend_labels: tuple[str, ...] = (), legend_position: str = "top", label_position: str = "") -> BytesIO:
    if frame.empty or not group or not series or stack not in frame.columns:
        return _empty_chart(title)
    axis_columns = _chart_axis_hierarchy(frame, distribution=True) or [group, series]
    data = frame[[*axis_columns, stack]].dropna()
    data.attrs = frame.attrs.copy()
    data = data[data[stack].astype(str).ne("(blank)")]
    data.attrs = frame.attrs.copy()
    combinations = _hierarchical_unique_keys(data, axis_columns)
    buckets = _distribution_buckets(data)
    if not combinations or not buckets:
        return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 125, 260, 1260, 475
    bar_width = max(20, min(96, width // max(len(combinations) * 2, 1)))
    bucket_colours = _distribution_bucket_colours(buckets, data)
    for tick in range(6):
        value = tick * 20
        y = top + height - tick / 5 * height
        draw.line((left, y, left + width, y), fill="#E4E9ED", width=1)
        label = f"{value}%"
        label_width = _text_width(draw, label, _font(16, True))
        draw.text((left - label_width - 12, y - 9), label, fill="#4E6271", font=_font(16, True))
    draw.line((left, top, left, top + height), fill="#AEBBC4", width=2)
    for index, key in enumerate(combinations):
        subset = data
        for column, value in zip(axis_columns, key, strict=True):
            subset = subset[subset[column].astype(str) == str(value)]
        total = max(len(subset), 1); x = left + index * (width / len(combinations)) + 10; running = 0
        for bucket_index, bucket in enumerate(buckets):
            value = len(subset[subset[stack] == bucket]) / total; segment = value * height; y = top + height - running - segment
            draw.rectangle((x, y, x + bar_width, y + segment), fill=bucket_colours.get((bucket,), _colour(bucket, bucket_index)))
            value_label = f"{value:.1%}"
            label_font = _font(17, True)
            label_box = draw.textbbox((0, 0), value_label, font=label_font)
            label_height = label_box[3] - label_box[1]
            def automatic_label() -> None:
                if _text_width(draw, value_label, label_font) + 10 <= bar_width and label_height + 8 <= segment:
                    _draw_inside_bar_label(
                        image, draw, value_label,
                        x=x, y=y, width=bar_width, height=segment,
                        fill="#FFFFFF", font=label_font,
                    )
                elif value > 0:
                    _draw_adjacent_stacked_bar_label(
                        draw, value_label, x=x, y=y, width=bar_width, height=segment,
                        bar_top=top, bar_bottom=top + height,
                        fill=colour, font=_font(12, True),
                    )
            colour = bucket_colours.get((bucket,), _colour(bucket, bucket_index))
            _draw_configured_bar_label(image, draw, value_label, x=x, y=y, width=bar_width, height=segment, colour=colour, font=label_font, position=label_position, horizontal=False, automatic=automatic_label)
            running += segment
    _draw_top_column_group_separators(
        draw,
        combinations,
        axis_columns,
        left=left,
        width=width,
        top=top,
        bottom=top + height,
    )
    _draw_hierarchical_axis_labels(image, draw, combinations, left, width, top, top + height)
    legend_buckets = _distribution_buckets(data, legend=True)
    _draw_chart_legend(draw, [(_legend_caption(legend_labels, index, bucket), bucket_colours.get((bucket,), _colour(bucket, index)), 2) for index, bucket in enumerate(legend_buckets[:8])], legend_position)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _combine_charts(title: str, charts: list[BytesIO]) -> BytesIO:
    """Place several chart grammars in a compact grid."""
    usable = [Image.open(chart).convert("RGB") for chart in charts]
    if not usable:
        return _empty_chart(title)
    image, _ = _canvas(title)
    columns = 2 if len(usable) > 1 else 1
    rows = (len(usable) + columns - 1) // columns
    width = image.width // columns
    height = (image.height - 80) // rows
    for index, chart in enumerate(usable):
        chart.thumbnail((width - 18, height - 10))
        column = index % columns
        row = index // columns
        x = column * width + (width - chart.width) // 2
        y = 80 + row * height + (height - chart.height) // 2
        image.paste(chart, (x, y))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _cdf_terminal_x_maximum(
    series_values: list[list[float]],
    low: float,
    fallback: float,
    minimum_separation: float = 0.015,
) -> float:
    """Trim only a converged tail after most CDF curves are effectively complete."""
    if len(series_values) < 2:
        return fallback
    required_completed_curves = math.ceil(len(series_values) * 0.80)
    # Sweep the already sorted curves once. The previous implementation
    # rescanned every point for every candidate x value, making large CDFs
    # quadratic.
    counts = [bisect_left(values, low) for values in series_values]
    events: list[tuple[float, int]] = []
    for series_index, (values, start) in enumerate(zip(series_values, counts, strict=True)):
        if start < len(values) and values[start] <= fallback:
            heapq.heappush(events, (values[start], series_index))
    minimum_levels: list[tuple[float, int, int]] = []
    maximum_levels: list[tuple[float, int, int]] = []
    completed: set[int] = set()
    while events:
        value = events[0][0]
        touched: set[int] = set()
        while events and events[0][0] == value:
            _event_value, series_index = heapq.heappop(events)
            values = series_values[series_index]
            counts[series_index] = bisect_right(values, value, lo=counts[series_index])
            touched.add(series_index)
            if counts[series_index] < len(values) and values[counts[series_index]] <= fallback:
                heapq.heappush(events, (values[counts[series_index]], series_index))
        for series_index in touched:
            level = counts[series_index] / len(series_values[series_index])
            if level > 0.99:
                completed.add(series_index)
                heapq.heappush(minimum_levels, (level, series_index, counts[series_index]))
                heapq.heappush(maximum_levels, (-level, series_index, counts[series_index]))
        while minimum_levels and counts[minimum_levels[0][1]] != minimum_levels[0][2]:
            heapq.heappop(minimum_levels)
        while maximum_levels and counts[maximum_levels[0][1]] != maximum_levels[0][2]:
            heapq.heappop(maximum_levels)
        # Never crop meaningful CDF data. A tail is eligible only once at
        # least 80% of curves (rounded up) have *exceeded* 99%, and those
        # completed curves have themselves converged too closely to
        # distinguish. A coincident minority must never truncate other
        # still-separated CDF curves.
        completed_curves_converged = (
            len(completed) >= required_completed_curves
            and minimum_levels
            and maximum_levels
            and -maximum_levels[0][0] - minimum_levels[0][0] < minimum_separation
        )
        if completed_curves_converged:
            return value
    return fallback


def _cdf_plot_geometry(legend_position: str, legend_rows: int = 1) -> tuple[int, int, int, int]:
    """Reserve a non-overlapping lane for a CDF legend."""
    if legend_position == "right":
        return 100, 135, 1190, 590
    if legend_position == "left":
        return 400, 135, 1020, 590
    if legend_position == "top":
        top = max(135, 80 + legend_rows * 29 + 26)
        return 100, top, 1320, max(360, 725 - top)
    if legend_position == "bottom":
        bottom = min(725, 900 - legend_rows * 29 - 66)
        return 100, 135, 1320, max(360, bottom - 135)
    return 100, 135, 1320, 590


def _cdf_domains(
    automatic_x_low: float,
    automatic_x_high: float,
    axis_x_range: str = "",
    axis_y_range: str = "",
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Overlay optional template bounds on the existing automatic CDF domains."""
    requested_x_low, requested_x_high = parse_axis_range(axis_x_range, "x")
    requested_y_low, requested_y_high = parse_axis_range(axis_y_range, "y")
    x_low = automatic_x_low if requested_x_low is None else requested_x_low
    x_high = automatic_x_high if requested_x_high is None else requested_x_high
    y_low = 0.0 if requested_y_low is None else requested_y_low / 100
    y_high = 1.0 if requested_y_high is None else requested_y_high / 100
    # A one-sided bound may lie beyond all observations. Keep a valid, empty
    # viewport rather than failing the complete report.
    if x_high <= x_low:
        if requested_x_low is not None and requested_x_high is None:
            x_high = x_low + 1
        elif requested_x_high is not None and requested_x_low is None:
            x_low = x_high - 1
        else:
            x_high = x_low + 1
    return (x_low, x_high), (y_low, y_high)


def _cdf_visible_points(values: list[float], low: float, high: float) -> list[tuple[float, float]]:
    """Return a clipped CDF polyline without collapsing vertical steps."""
    if not values:
        return []
    total = len(values)
    start = bisect_left(values, low)
    end = bisect_right(values, high)
    points: list[tuple[float, float]] = []
    # If the viewport starts after observations that are no longer visible,
    # anchor the line at their cumulative level. When ``low`` is the natural
    # minimum there is no synthetic zero-percent point: retaining every
    # repeated minimum reproduces the original vertical CDF step.
    if start:
        points.append((low, start / total))
    for index in range(start, end):
        value = float(values[index])
        cumulative = (index + 1) / total
        points.append((value, cumulative))
    terminal = end / total
    if not points or points[-1][0] != high:
        points.append((high, terminal))
    return points


def _render_cdf_line(
    title: str,
    frame: pd.DataFrame,
    group: str | None,
    period: str | None,
    metric: str | None,
    legend_labels: tuple[str, ...] = (),
    legend_position: str = "top",
    layout_legend_position: str | None = None,
    axis_x_range: str = "",
    axis_y_range: str = "",
    exclude_null_empty: bool = False,
    exclude_zero: bool = False,
) -> BytesIO:
    if frame.empty or not group or not metric: return _empty_chart(title)
    campaign_column = _period_column(frame)
    # A CDF series is defined by the complete aggregation hierarchy, not by
    # the flattened primary/series pair.  This preserves every combination
    # when dimensions are split between Rows Aggregation and Column
    # Aggregation, or when several dimensions live on either one.
    hierarchy_columns = _chart_axis_hierarchy(frame)
    grouping_columns = hierarchy_columns or [
        *([group] if group else []),
        *([period] if period and period != group else []),
    ]
    columns = list(dict.fromkeys([*grouping_columns, metric, *([campaign_column] if campaign_column else [])]))
    data = frame[columns].copy()
    data.attrs = frame.attrs.copy()
    if campaign_column:
        data["__cdf_campaign"] = data[campaign_column].fillna("(blank)").astype(str).map(_campaign_display_value)
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    # Optional campaign metadata must not discard otherwise valid CDF samples.
    data = data.dropna(subset=[metric, *grouping_columns])
    if exclude_zero:
        data = data[data[metric].ne(0)]
    if data.empty: return _empty_chart(title)
    combinations = _hierarchical_unique_keys(data, grouping_columns)
    series_data: list[tuple[tuple[str, ...], pd.DataFrame, list[float]]] = []
    for combination in combinations:
        mask = pd.Series(True, index=data.index)
        for column, value in zip(grouping_columns, combination, strict=True):
            mask &= data[column].astype(str).eq(str(value))
        subset = data.loc[mask]
        values = subset[metric].sort_values().tolist()
        if values:
            series_data.append((combination, subset, values))
    if not series_data:
        return _empty_chart(title)
    low = float(data[metric].min())
    observed_high = float(data[metric].max())
    series_values = [values for _, _, values in series_data]
    automatic_high = _cdf_terminal_x_maximum(series_values, low, observed_high)
    automatic_high = automatic_high if automatic_high > low else low + 1
    (low, high), (y_low, y_high) = _cdf_domains(low, automatic_high, axis_x_range, axis_y_range)
    layout_position = layout_legend_position or legend_position
    series_labels = [
        _legend_key_caption(combination, grouping_columns, data, legend_labels)
        for combination, _subset, _values in series_data
    ]
    legend_columns = _horizontal_legend_columns(series_labels, 11, line_markers=True)
    legend_rows = max(1, math.ceil(len(series_labels) / legend_columns))
    image, draw = _canvas(title)
    left, top, width, height = _cdf_plot_geometry(layout_position, legend_rows)
    # Colour policy is driven by the template's declared dimensions: operator
    # families are used only for genuine multi-operator comparisons.
    comparison_colours = _series_colours(combinations, grouping_columns, data, line_chart=True)
    line_dashes = _series_line_dashes(combinations, grouping_columns, data)
    # A campaign is the temporal comparison within an operator/vendor.  Keep
    # that relationship visible even in monochrome printouts by making newer
    # campaigns progressively thicker than their earlier counterparts.
    series_campaigns = [
        (
            combination,
            subset["__cdf_campaign"].astype(str).unique() if "__cdf_campaign" in subset else (),
        )
        for combination, subset, _values in series_data
    ]
    line_widths = _cdf_campaign_line_widths(series_campaigns, grouping_columns, data)
    legend_items: list[tuple[str, str, int, tuple[int, ...]]] = []
    for index, (combination, subset, values) in enumerate(series_data):
        visible_points = _cdf_visible_points(values, low, high)
        if not visible_points:
            continue
        label = series_labels[index]
        points = [
            (
                left + (value - low) / (high - low) * width,
                top + height - (cumulative - y_low) / (y_high - y_low) * height,
            )
            for value, cumulative in visible_points if y_low <= cumulative <= y_high
        ]
        if not points:
            continue
        line_width = line_widths.get(tuple(str(value) for value in combination), 4)
        colour = comparison_colours.get(combination, _colour(label, index))
        dash = line_dashes.get(combination, ())
        _draw_patterned_polyline(draw, points, colour, line_width, dash)
        legend_items.append((label, colour, line_width, dash))
    for tick in range(0, 6):
        cumulative = y_low + (y_high - y_low) * tick / 5
        y = top + height - tick / 5 * height; draw.line((left, y, left + width, y), fill="#E4E9ED", width=1); draw.text((left - 84, y - 10), f"{cumulative * 100:.0f}%", fill="#4E6271", font=_font(18, True))
    for tick in range(0, 6):
        value = low + (high - low) * tick / 5
        x = left + width * tick / 5
        draw.line((x, top + height, x, top + height + 7), fill="#62727E", width=1)
        draw.text((x - 18, top + height + 7), f"{value:.1f}", fill="#4E6271", font=_font(16, True))
    draw.text((left + width / 2 - 70, top + height + 31), metric.replace("_", " "), fill="#405765", font=_font(20, True))
    if not legend_labels:
        legend_items = _group_vendor_legend_items(legend_items, data)
    _draw_chart_legend(draw, legend_items, legend_position, font_size=11, line_markers=True)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _osm_world_coordinates(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    """Convert WGS84 coordinates to global Web-Mercator pixels."""
    latitude = max(-85.05112878, min(85.05112878, latitude))
    scale = OSM_TILE_SIZE * (2 ** zoom)
    x = (longitude + 180.0) / 360.0 * scale
    latitude_radians = math.radians(latitude)
    y = (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2.0 * scale
    return x, y


def _osm_tile_path(zoom: int, x: int, y: int) -> Path:
    return OSM_TILE_CACHE_DIR / str(zoom) / str(x) / f'{y}.png'


def _osm_map_tile_geometry(
    lon_low: float, lon_high: float, lat_low: float, lat_high: float,
) -> tuple[int, int, int, int, int, tuple[float, float], tuple[float, float]]:
    """Choose the shared OSM zoom, tile range and projected viewport."""
    for zoom in range(OSM_TILE_MAX_ZOOM, 1, -1):
        top_left = _osm_world_coordinates(lat_high, lon_low, zoom)
        bottom_right = _osm_world_coordinates(lat_low, lon_high, zoom)
        tile_left, tile_top = int(top_left[0] // OSM_TILE_SIZE), int(top_left[1] // OSM_TILE_SIZE)
        tile_right, tile_bottom = int(bottom_right[0] // OSM_TILE_SIZE), int(bottom_right[1] // OSM_TILE_SIZE)
        tile_count = (tile_right - tile_left + 1) * (tile_bottom - tile_top + 1)
        if tile_count <= OSM_TILE_MAX_COUNT:
            return zoom, tile_left, tile_top, tile_right, tile_bottom, top_left, bottom_right
    zoom = 2
    top_left = _osm_world_coordinates(lat_high, lon_low, zoom)
    bottom_right = _osm_world_coordinates(lat_low, lon_high, zoom)
    return zoom, 0, 0, 3, 3, top_left, bottom_right


def _load_osm_tile(zoom: int, x: int, y: int) -> Image.Image | None:
    """Read one cached OSM tile or retrieve it once for a Map chart."""
    tile_path = _osm_tile_path(zoom, x, y)
    try:
        if tile_path.is_file():
            with Image.open(tile_path) as cached:
                return cached.convert('RGB')
        request = Request(
            f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
            headers={'User-Agent': 'DashboardAnalytic/0.2.3 (cached Map chart renderer)'},
        )
        with urlopen(request, timeout=2.5, context=OSM_TLS_CONTEXT) as response:
            payload = response.read()
        with Image.open(BytesIO(payload)) as downloaded:
            image = downloaded.convert('RGB')
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = tile_path.with_suffix('.tmp')
        image.save(temporary_path, format='PNG')
        os.replace(temporary_path, tile_path)
        return image
    except (OSError, URLError, ValueError):
        return None


def _osm_map_background(lon_low: float, lon_high: float, lat_low: float, lat_high: float, width: int, height: int) -> tuple[Image.Image | None, Callable[[float, float], tuple[float, float]]]:
    """Create a cached OSM base layer and coordinate transform for one chart."""
    zoom, tile_left, tile_top, tile_right, tile_bottom, top_left, bottom_right = _osm_map_tile_geometry(
        lon_low, lon_high, lat_low, lat_high,
    )
    tile_columns, tile_rows = tile_right - tile_left + 1, tile_bottom - tile_top + 1
    mosaic = Image.new('RGB', (tile_columns * OSM_TILE_SIZE, tile_rows * OSM_TILE_SIZE), '#EDF4F0')
    coordinates = [(x, y) for y in range(tile_top, tile_bottom + 1) for x in range(tile_left, tile_right + 1)]
    def fetch(coordinate: tuple[int, int]) -> tuple[tuple[int, int], Image.Image | None]:
        x, y = coordinate
        return coordinate, _load_osm_tile(zoom, x, y)
    with ThreadPoolExecutor(max_workers=min(6, len(coordinates))) as executor:
        for (x, y), tile in executor.map(fetch, coordinates):
            if tile is not None:
                mosaic.paste(tile, ((x - tile_left) * OSM_TILE_SIZE, (y - tile_top) * OSM_TILE_SIZE))
    crop = (
        int(max(0, top_left[0] - tile_left * OSM_TILE_SIZE)),
        int(max(0, top_left[1] - tile_top * OSM_TILE_SIZE)),
        int(min(mosaic.width, math.ceil(bottom_right[0] - tile_left * OSM_TILE_SIZE))),
        int(min(mosaic.height, math.ceil(bottom_right[1] - tile_top * OSM_TILE_SIZE))),
    )
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        return None, lambda latitude, longitude: (0.0, 0.0)
    background = mosaic.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
    source_width, source_height = bottom_right[0] - top_left[0], bottom_right[1] - top_left[1]
    def project(latitude: float, longitude: float) -> tuple[float, float]:
        x, y = _osm_world_coordinates(latitude, longitude, zoom)
        return ((x - top_left[0]) / source_width * width, (y - top_left[1]) / source_height * height)
    return background, project


def _render_map(title: str, frame: pd.DataFrame, group: str | None, series: str | None, latitude: str | None, longitude: str | None, legend_labels: tuple[str, ...] = (), legend_position: str = "top") -> BytesIO:
    """Render a self-contained latitude/longitude point map for report output."""
    if frame.empty or not latitude or not longitude:
        return _empty_chart(title)
    columns = [latitude, longitude, *([group] if group else []), *([series] if series and series != group else [])]
    data = frame[columns].copy(); data.attrs = frame.attrs.copy()
    data[latitude] = pd.to_numeric(data[latitude], errors="coerce"); data[longitude] = pd.to_numeric(data[longitude], errors="coerce")
    data = data.dropna(subset=[latitude, longitude])
    if data.empty:
        return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 120, 135, 1260, 610
    lon_low, lon_high = float(data[longitude].min()), float(data[longitude].max()); lat_low, lat_high = float(data[latitude].min()), float(data[latitude].max())
    lon_padding = max((lon_high - lon_low) * .06, .004); lat_padding = max((lat_high - lat_low) * .06, .004)
    lon_low -= lon_padding; lon_high += lon_padding; lat_low -= lat_padding; lat_high += lat_padding
    background, project = _osm_map_background(lon_low, lon_high, lat_low, lat_high, width, height)
    if background is not None:
        image.paste(background, (left, top))
    else:
        draw.rectangle((left, top, left + width, top + height), fill="#EDF4F0", outline="#B9CDC4", width=2)
        for fraction in (.2, .4, .6, .8):
            draw.line((left + width * fraction, top, left + width * fraction, top + height), fill="#D8E5DF", width=1)
            draw.line((left, top + height * fraction, left + width, top + height * fraction), fill="#D8E5DF", width=1)
    draw.rectangle((left, top, left + width, top + height), outline="#B9CDC4", width=2)
    key_columns = [group, series] if series and group and series != group else [group] if group else []
    # Keep each point's colour key in an indexable array.  Building the keys
    # and drawing rows with a strict ``zip`` made a Chart Set fail whenever a
    # pandas iterator exposed fewer rows than a parallel key iterator.  Both
    # arrays are now derived from this filtered map frame and indexed together.
    key_values = (
        data[key_columns].fillna('(blank)').astype(str).to_numpy()
        if key_columns else None
    )
    keys = [tuple(values) for values in key_values] if key_values is not None else [('All',)] * len(data)
    unique_keys = list(dict.fromkeys(keys)); colours = _series_colours(unique_keys, key_columns, data)
    legend_items: list[tuple[str, str, int]] = []
    for index, row in enumerate(data.itertuples(index=False)):
        key = keys[index]
        lat = float(getattr(row, latitude)); lon = float(getattr(row, longitude))
        if background is not None:
            point_x, point_y = project(lat, lon); x, y = left + point_x, top + point_y
        else:
            x = left + (lon - lon_low) / (lon_high - lon_low) * width; y = top + height - (lat - lat_low) / (lat_high - lat_low) * height
        colour = colours.get(key, _colour(key, index)); draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=colour, outline="#FFFFFF", width=1)
    for index, key in enumerate(unique_keys):
        label = _legend_key_caption(key, key_columns, data, legend_labels) or ' · '.join(key)
        legend_items.append((label, colours.get(key, _colour(key, index)), 2))
    _draw_chart_legend(draw, legend_items[:10], legend_position, font_size=13)
    if background is not None:
        draw.rectangle((left + width - 210, top + height - 25, left + width - 4, top + height - 4), fill="#FFFFFF")
        draw.text((left + width - 204, top + height - 22), '© OpenStreetMap contributors', fill="#405765", font=_font(11, False))
    draw.text((left, top + height + 16), longitude.replace('_', ' '), fill="#405765", font=_font(17, True)); draw.text((26, top - 25), latitude.replace('_', ' '), fill="#405765", font=_font(17, True))
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_scatter(title: str, frame: pd.DataFrame, group: str | None, metric: str | None, x_metric: str | None, legend_labels: tuple[str, ...] = (), legend_position: str = "top") -> BytesIO:
    if frame.empty or not group or not metric or not x_metric: return _empty_chart(title)
    data = frame[[group, metric, x_metric]].copy(); data.attrs = frame.attrs.copy(); data[metric] = pd.to_numeric(data[metric], errors="coerce"); data[x_metric] = pd.to_numeric(data[x_metric], errors="coerce"); data = data.dropna()
    if data.empty: return _empty_chart(title)
    image, draw = _canvas(title); left, top, width, height = 130, 120, 1220, 600
    x_low, x_high = float(data[x_metric].min()), float(data[x_metric].max()); y_low, y_high = float(data[metric].min()), float(data[metric].max()); x_high = x_high if x_high > x_low else x_low + 1; y_high = y_high if y_high > y_low else y_low + 1
    group_keys = [(str(label),) for label in data[group].drop_duplicates().tolist()]
    group_colours = _series_colours(group_keys, [group], data)
    legend_items: list[tuple[str, str, int]] = []
    for index, (label, subset) in enumerate(data.groupby(group, sort=False)):
        for x_value, y_value in subset[[x_metric, metric]].itertuples(index=False):
            x = left + (x_value - x_low) / (x_high - x_low) * width; y = top + height - (y_value - y_low) / (y_high - y_low) * height
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=group_colours.get((str(label),), _colour(label, index)))
        legend_items.append((_legend_caption(legend_labels, index, label), group_colours.get((str(label),), _colour(label, index)), 2))
    for tick in range(0, 6):
        x = left + width * tick / 5; y = top + height - height * tick / 5
        x_value = x_low + (x_high - x_low) * tick / 5; y_value = y_low + (y_high - y_low) * tick / 5
        draw.line((x, top + height, x, top + height + 7), fill="#62727E", width=1)
        draw.line((left - 7, y, left, y), fill="#62727E", width=1)
        draw.text((x - 18, top + height + 7), f"{x_value:.0f}", fill="#4E6271", font=_font(16, True))
        draw.text((68, y - 9), f"{y_value:.1f}", fill="#4E6271", font=_font(16, True))
    draw.text((left + width / 2 - 120, top + height + 30), x_metric.replace("_", " "), fill="#405765", font=_font(20, True)); draw.text((40, 90), metric.replace("_", " "), fill="#405765", font=_font(20, True))
    _draw_chart_legend(draw, legend_items, legend_position, font_size=14)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0); return output


def _render_mean_column(
    title: str,
    frame: pd.DataFrame,
    group: str | None,
    series: str | None,
    metric: str | None,
    aggregation: str = "mean",
    legend_dimensions: tuple[str, ...] = (),
    legend_position: str = "top",
    label_position: str = "",
) -> BytesIO:
    if frame.empty or not group or not metric:
        return _empty_chart(title)
    axis_columns = _chart_axis_hierarchy(frame) or ([group, series] if series and series != group else [group])
    data = frame[[*axis_columns, metric]].copy()
    data.attrs = frame.attrs.copy()
    means = _aggregate_metric(data, axis_columns, metric, aggregation)
    if means.empty:
        return _empty_chart(title)
    image, draw = _canvas(title)
    # Reserve a true y-axis lane for the KPI label and a generous lower band
    # for a uniformly rotated hierarchy of column captions.
    left, top, chart_width, baseline, maximum = 155, 280, 1165, 680, max(float(means.max()), 1.0)
    bar_width = min(150, max(30, chart_width / max(len(means) * 1.7, 1)))
    keys = [label if isinstance(label, tuple) else (label,) for label in means.index]
    group_colours = _series_colours(keys, axis_columns, data)
    for index, (label, value) in enumerate(means.items()):
        height = (baseline - top) * float(value) / maximum
        x = left + (index + .5) * chart_width / len(means) - bar_width / 2
        y = baseline - height
        colour = group_colours.get(keys[index], _colour(label, index))
        value_label = f"{float(value):.2f}"
        draw.rectangle((x, y, x + bar_width, baseline), fill=colour)
        label_font = _font(24, True)
        def automatic_label() -> None:
            if height >= 46 and _draw_inside_bar_label(image, draw, value_label, x=x, y=y, width=bar_width, height=height, fill="white", font=label_font):
                return
            label_width = _text_width(draw, value_label, label_font)
            draw.text((x + (bar_width - label_width) / 2, y - 29), value_label, fill=colour, font=label_font)
        _draw_configured_bar_label(image, draw, value_label, x=x, y=y, width=bar_width, height=height, colour=colour, font=label_font, position=label_position, horizontal=False, automatic=automatic_label)
    _draw_top_column_group_separators(
        draw,
        keys,
        axis_columns,
        left=left,
        width=chart_width,
        top=top,
        bottom=baseline,
    )
    _draw_hierarchical_axis_labels(image, draw, keys, left, chart_width, top, baseline)
    _draw_vertical_label(
        image, metric.replace("_", " "), centre_x=48, centre_y=(top + baseline) / 2,
        fill="#405765", font=_font(21, True),
    )
    if legend_dimensions:
        legend_items: list[tuple[str, str, int]] = []
        seen_captions: set[str] = set()
        for index, key in enumerate(keys):
            caption = _legend_key_caption(key, axis_columns, data, legend_dimensions)
            if caption in seen_captions:
                continue
            seen_captions.add(caption)
            legend_items.append((caption, group_colours.get(key, _colour(key, index)), 2))
        _draw_chart_legend(draw, legend_items, legend_position)
    output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
    return output


def _render_table(
    title: str,
    frame: pd.DataFrame,
    group: str | None,
    series: str | None,
    metric: str | None,
    *,
    percentiles: bool = False,
    aggregation: str | None = None,
) -> BytesIO:
    """Render numeric summaries or categorical ratios from a template table."""
    if frame.empty or not group or not metric:
        return _empty_chart(title)
    data = frame[[group, series, metric]].copy() if series else frame[[group, metric]].copy()
    has_series = bool(series) and not data[series].fillna("(all)").astype(str).eq("(all)").all()
    value_suffix = ""
    if aggregation:
        dimensions = [group, *([series] if has_series else [])]
        values = _aggregate_metric(data, dimensions, metric, aggregation)
        table = values.unstack(series) if has_series else values.to_frame(aggregation.upper())
    else:
        numeric_metric = pd.to_numeric(data[metric], errors="coerce")
        if numeric_metric.notna().any():
            data[metric] = numeric_metric
            data = data.dropna(subset=[metric])
            if percentiles:
                table = data.groupby(group, sort=False)[metric].quantile([.1, .5, .9]).unstack()
                table.columns = ["P10", "P50", "P90"]
            elif has_series:
                table = data.pivot_table(index=group, columns=series, values=metric, aggfunc="mean", sort=False)
            else:
                table = data.groupby(group, sort=False)[metric].mean().to_frame("Value")
        else:
            # Tableau count/percent-of-total tables commonly use a categorical KPI
            # such as Test_Result. Preserve that meaning instead of coercing every
            # value to NaN and returning an empty chart.
            categorical = data.dropna(subset=[group, metric]).copy()
            if categorical.empty:
                return _empty_chart(title)
            columns = [series, metric] if has_series else [metric]
            table = pd.crosstab(categorical[group], [categorical[column] for column in columns], normalize="index") * 100
            value_suffix = "%"
    image, draw = _canvas(title)
    headers = [str(table.index.name or "Category")] + [str(value) for value in table.columns]
    rows = [
        (str(index), *["" if pd.isna(value) else f"{float(value):.2f}{value_suffix}" for value in values])
        for index, values in table.head(18).iterrows()
    ]
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


KPI_AGGREGATION_ALIASES = {
    "SUM": "sum",
    "COUNT": "count",
    "COUNTD": "countd",
    "AVERAGE": "mean",
    "AVG": "mean",
    "MEAN": "mean",
    "MAX": "max",
    "MIN": "min",
    "MEDIAN": "median",
}


def parse_kpi_expression(value: str) -> tuple[str, str | None]:
    """Return the physical KPI field and an optional explicit aggregation."""
    raw = str(value or "").strip()
    match = re.fullmatch(
        r"(?i)(SUM|COUNTD|COUNT|AVERAGE|AVG|MEAN|MAX|MIN|MEDIAN)\s*\(\s*(.+?)\s*\)",
        raw,
    )
    if not match:
        return raw.strip(" `"), None
    operation, field = match.groups()
    return field.strip(" `"), KPI_AGGREGATION_ALIASES[operation.upper()]


def catalog_kpi_fields(value: str) -> tuple[str, ...]:
    """Return the physical CDR fields referenced by a KPI definition."""
    return tuple(
        parse_kpi_expression(part)[0]
        for part in re.split(r"\s+vs\s+|\s*\|\s*", str(value or ""), flags=re.I)
        if part.strip() and parse_kpi_expression(part)[0]
    )


def _aggregate_metric(
    frame: pd.DataFrame, dimensions: list[str], metric: str, aggregation: str,
) -> pd.Series:
    """Aggregate one KPI with Tableau-compatible count and numeric semantics."""
    working = frame[[*dimensions, metric]].copy()
    if aggregation not in {"count", "countd"}:
        working[metric] = pd.to_numeric(working[metric], errors="coerce")
    grouped = working.groupby(dimensions, dropna=False, sort=False)[metric] if dimensions else None
    if dimensions:
        if aggregation == "count":
            return grouped.count()
        if aggregation == "countd":
            return grouped.nunique(dropna=True)
        return getattr(grouped, aggregation)()
    series = working[metric]
    if aggregation == "count":
        value = series.count()
    elif aggregation == "countd":
        value = series.nunique(dropna=True)
    else:
        value = getattr(series, aggregation)()
    return pd.Series([value], index=pd.Index(["All"], name="Category"))


def _catalog_spec(entry: CatalogEntry) -> dict:
    chart_type = entry.chart_type.casefold()
    raw_metric_parts = tuple(part for part in re.split(r"\s+vs\s+", entry.kpi, flags=re.I) if part.strip())
    metric_parts = tuple(parse_kpi_expression(part)[0] for part in raw_metric_parts)
    _field, aggregation = parse_kpi_expression(raw_metric_parts[0] if raw_metric_parts else entry.kpi)
    spec: dict = {
        "source": entry.source_kind,
        "metric": metric_parts[:1] or (entry.kpi,),
        "aggregation": aggregation,
    }
    if chart_type == "multi kpi cdf lines":
        metrics = tuple(parse_kpi_expression(part)[0] for part in entry.kpi.split("|") if part.strip())
        spec["kind"] = "multi_cdf"
        spec["metric"] = metrics[:1]
        spec["metrics"] = metrics
    elif "scatter" in chart_type:
        spec["kind"] = "scatter"
        spec["x_metric"] = metric_parts[1:] or ("Playing_RSRP_NR_Avg", "NR_RSRP_Avg")
    elif chart_type == "map":
        spec["kind"] = "map"
        spec["x_metric"] = metric_parts[1:] or ("Test_Start_Longitude", "Test Start Longitude")
    elif chart_type == "count stacked horizontal bars":
        spec["kind"] = "failure_count"
    elif "100%" in chart_type or chart_type == "threshold stacked vertical bars":
        spec["kind"] = "quality_100" if chart_type == "threshold stacked vertical bars" or any(token in entry.kpi.casefold() for token in ("lq", "polqa")) else "status_100"
        if spec["kind"] == "quality_100":
            spec["threshold"] = _catalog_threshold(entry)
    else:
        spec["kind"] = "cdf_mean"
    return spec


def prepare_catalog_chart_preview_frame(
    frame: pd.DataFrame, entry: CatalogEntry, *, multivendor: bool = False,
    template_filters_applied: bool = False,
) -> tuple[pd.DataFrame, CatalogEntry]:
    """Return reusable chart rows after source and template filtering."""
    render_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
    normalised = frame if frame.attrs.get('operator_aliases_normalized') else normalise_operator_aliases(frame)
    spec = _catalog_spec(render_entry)
    filtered, _group, _period = _source_for_spec({render_entry.source_kind: normalised}, spec, multivendor)
    filtered.attrs["catalogue_calculated_dimensions"] = render_entry.calculated_dimensions
    filtered.attrs["catalogue_cdr_source"] = render_entry.cdr_source
    metric = _metric_column(filtered, spec)
    filtered = filtered if template_filters_applied else _apply_catalog_filters(
        filtered, render_entry, multivendor, metric,
    )
    return _exclude_chart_values(filtered, render_entry, spec, multivendor), render_entry


def _exclude_chart_values(
    frame: pd.DataFrame,
    entry: CatalogEntry,
    spec: dict[str, object],
    multivendor: bool,
) -> pd.DataFrame:
    """Exclude configured missing and/or exact-zero values from plotted measures."""
    if (not entry.exclude_null_empty and not entry.exclude_zero) or frame.empty:
        return frame
    columns: list[str] = []
    metric = _metric_column(frame, spec)
    if metric and spec.get("kind") != "multi_cdf":
        columns.append(metric)
    if spec.get("kind") in {"scatter", "map"}:
        resolved = _column(frame, spec.get("x_metric", ()))
        if resolved:
            columns.append(resolved)
    mask = pd.Series(True, index=frame.index)
    for column in dict.fromkeys(columns):
        series = frame[column]
        populated = series.notna() & series.astype(str).str.strip().ne("")
        numeric = pd.to_numeric(series, errors="coerce")
        if entry.exclude_null_empty:
            mask &= populated
        if entry.exclude_zero:
            mask &= ~(numeric.notna() & numeric.eq(0))
    result = frame.loc[mask].copy()
    result.attrs = frame.attrs.copy()
    return result


INTERACTIVE_CHART_POINTS_PER_SERIES = 900
INTERACTIVE_SCATTER_POINTS_PER_SERIES = 900
# A Canvas chart with tens of thousands of one-sample CDF lines is neither
# legible nor responsive. Keep a bounded number of meaningful comparison
# curves, dropping the most detailed leading hierarchy levels as needed.
INTERACTIVE_CDF_SERIES_LIMIT = 120


def _interactive_sample(values: list[object], limit: int) -> list[tuple[int, object]]:
    """Keep a stable visual sample while retaining both ends of an ordered series."""
    if len(values) <= limit:
        return list(enumerate(values))
    indexes = sorted({round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)})
    return [(index, values[index]) for index in indexes]


def _chart_payload_value(value: object) -> str:
    """Return a stable JSON/display value for a chart hierarchy member."""
    return "(blank)" if pd.isna(value) else str(value)


def _chart_payload_legend(
    entry: CatalogEntry,
    frame: pd.DataFrame,
    metric: str | None,
    fallback: list[tuple[str, str, int]] | None = None,
    *,
    chart_type: str,
    line_markers: bool = False,
) -> dict[str, object]:
    """Resolve the browser legend with the same rules as the PNG renderer."""
    plotted_series_types = {"cdf", "status_100", "failure_count", "distribution", "map", "scatter"}
    if fallback and chart_type in plotted_series_types:
        # These charts colour segments or points from their renderer-specific
        # series. A grouping field can describe the axis, but it cannot safely
        # replace the colour key for those plotted values.
        items = fallback
        manual_labels = _legend_labels(entry.legend)
        if manual_labels and len(manual_labels) == len(fallback):
            items = [
                (manual_labels[index], colour, width)
                for index, (_label, colour, width) in enumerate(fallback)
            ]
    else:
        items = (fallback or []) if _legend_labels(entry.legend) else _resolved_legend_items(entry, frame, metric)
    if chart_type == "cdf" and not _legend_labels(entry.legend):
        items = _group_vendor_legend_items(list(items), frame)
    return {
        "position": parse_legend_position(entry.legend_position),
        "line_markers": line_markers,
        "items": [
            {"label": str(label), "colour": colour, "width": int(width)}
            for label, colour, width in items
        ],
    }


def _chart_payload_base(
    chart_type: str,
    title: str,
    entry: CatalogEntry,
    frame: pd.DataFrame,
    metric: str | None,
    fallback_legend: list[tuple[str, str, int]] | None = None,
    *,
    line_markers: bool = False,
    show_legend: bool = True,
) -> dict[str, object]:
    """Create the fixed 1600 x 900 model used by both chart presentations."""
    x_range = parse_axis_range(entry.axis_x_range, "x")
    y_range = parse_axis_range(entry.axis_y_range, "y")
    return {
        "renderer": "catalog-v2",
        "width": 1600,
        "height": 900,
        "type": chart_type,
        "title": title,
        "legend": (
            _chart_payload_legend(
                entry, frame, metric, fallback_legend, chart_type=chart_type, line_markers=line_markers,
            ) if show_legend else {"position": "right", "line_markers": False, "items": []}
        ),
        "label_position": entry.label_position,
        "axis_ranges": {"x": list(x_range), "y": list(y_range)},
    }


def _configured_axis_domain(
    entry: CatalogEntry,
    axis: str,
    automatic_low: float,
    automatic_high: float,
    *,
    percentage: bool = False,
) -> list[float]:
    """Apply an optional template range to a numeric Canvas axis."""
    requested_low, requested_high = parse_axis_range(
        entry.axis_x_range if axis.casefold() == "x" else entry.axis_y_range,
        axis,
    )
    scale = 100.0 if percentage else 1.0
    low = float(automatic_low) if requested_low is None else float(requested_low) / scale
    high = float(automatic_high) if requested_high is None else float(requested_high) / scale
    if low >= high:
        span = max(abs(low), abs(high), 1.0) * 0.05
        if requested_low is not None and requested_high is None:
            high = low + span
        elif requested_high is not None and requested_low is None:
            low = high - span
    return [low, high]


def catalog_chart_payload(
    frame: pd.DataFrame,
    entry: CatalogEntry,
    *,
    multivendor: bool = False,
    prefiltered: bool = False,
) -> dict[str, object]:
    """Build a browser model using the report renderer's exact chart semantics.

    The payload retains the historical renderer's aggregation hierarchy,
    ordering, colours, legend resolution and logical 1600 x 900 geometry. The
    browser only performs the inexpensive final paint and tooltip hit testing.
    """
    render_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
    spec = _catalog_spec(render_entry)
    title = render_entry.chart_title or render_entry.slide_title
    if prefiltered:
        # Grouping adds derived columns but never mutates a source column.
        # A shallow frame copy avoids duplicating a potentially large filtered
        # selection before every Canvas model.
        filtered = frame.copy(deep=False)
    else:
        source_frame = (
            frame if frame.attrs.get("operator_aliases_normalized")
            else normalise_operator_aliases(frame)
        )
        filtered, _group, _period = _source_for_spec({render_entry.source_kind: source_frame}, spec, multivendor)
        metric = _metric_column(filtered, spec)
        filtered = _apply_catalog_filters(filtered, render_entry, multivendor, metric)
    filtered.attrs["catalogue_calculated_dimensions"] = render_entry.calculated_dimensions
    filtered.attrs["catalogue_cdr_source"] = render_entry.cdr_source
    filtered = _exclude_chart_values(filtered, render_entry, spec, multivendor)
    metric = _metric_column(filtered, spec)
    try:
        data, group, period = _apply_catalog_grouping(filtered, render_entry, multivendor, metric)
    except ValueError:
        return {
            **_chart_payload_base("empty", title, render_entry, filtered, metric),
            "message": "No valid samples for this KPI and technology filter",
        }
    if data.empty:
        return {
            **_chart_payload_base("empty", title, render_entry, data, metric),
            "message": "No valid samples for this KPI and technology filter",
        }

    chart_type = render_entry.chart_type.casefold()
    if chart_type != "distribution stacked vertical bars" and "__catalog_stack" in data.columns and period:
        data[period] = data[period].astype(str) + " · " + data["__catalog_stack"].astype(str)

    hierarchy_columns = sorted(
        [column for column in data.columns if column.startswith("__catalog_row_") or column.startswith("__catalog_column_")],
        key=lambda column: (0 if column.startswith("__catalog_row_") else 1, int(column.rsplit("_", 1)[1])),
    )
    row_hierarchy = [column for column in hierarchy_columns if column.startswith("__catalog_row_")]
    column_hierarchy = [column for column in hierarchy_columns if column.startswith("__catalog_column_")]

    def serialise_key(key: tuple[object, ...]) -> list[str]:
        return [_chart_payload_value(value) for value in key]

    def empty(message: str) -> dict[str, object]:
        return {
            **_chart_payload_base("empty", title, render_entry, data, metric),
            "message": message,
        }

    def cdf_model(candidate_metric: str, candidate_title: str) -> dict[str, object] | None:
        campaign_column = _period_column(data)
        grouping_columns = _chart_axis_hierarchy(data) or list(dict.fromkeys(
            [*([group] if group else []), *([period] if period and period != group else [])]
        ))
        columns = list(dict.fromkeys([
            *grouping_columns, candidate_metric, *([campaign_column] if campaign_column else []),
        ]))
        numeric = data[columns].copy()
        numeric.attrs = data.attrs.copy()
        if campaign_column:
            campaign_values = numeric[campaign_column].fillna("(blank)").astype(str)
            campaign_labels = {value: _campaign_display_value(value) for value in campaign_values.unique()}
            numeric["__cdf_campaign"] = campaign_values.map(campaign_labels)
        numeric[candidate_metric] = pd.to_numeric(numeric[candidate_metric], errors="coerce")
        numeric = numeric.dropna(subset=[candidate_metric, *grouping_columns])
        if render_entry.exclude_zero:
            numeric = numeric[numeric[candidate_metric].ne(0)]
        if numeric.empty:
            return None
        # Some imported Tableau catalogues include per-test identifiers ahead
        # of Operator. Those identifiers can turn one CDF into tens of
        # thousands of single-point lines. Remove only the leading overly
        # granular levels until the visual has a usable bounded series count;
        # the remaining declared dimensions still aggregate every matching
        # sample and keep the comparison meaningful.
        def grouped_indexes(columns: list[str]):
            grouper = columns[0] if len(columns) == 1 else columns
            # Pandas deep-copies DataFrame attrs while splitting groups. The
            # attrs describe catalogue metadata and are not used to find CDF
            # membership, so remove them from this short-lived grouping view.
            grouping_view = numeric[columns].copy(deep=False)
            grouping_view.attrs = {}
            return grouping_view.groupby(grouper, sort=False, dropna=False).indices

        while len(grouping_columns) > 1:
            unique_series = len(grouped_indexes(grouping_columns))
            if unique_series <= INTERACTIVE_CDF_SERIES_LIMIT:
                break
            grouping_columns = grouping_columns[1:]
        if grouping_columns:
            raw_positions = grouped_indexes(grouping_columns)
            # Iterating a pandas GroupBy materialises one DataFrame for every
            # group.  A CDF can have thousands of groups, so that creates an
            # enormous number of copies (and their DataFrame attrs) before
            # the first curve is produced.  Group indices preserve the same
            # group membership without creating those transient frames.
            grouped_positions = {
                tuple(str(value) for value in (key if isinstance(key, tuple) else (key,))): positions
                for key, positions in raw_positions.items()
            }
            combinations = list(grouped_positions)
            if len(grouping_columns) > 1:
                ordered_combinations: list[tuple[str, ...]] = []

                def visit(keys: list[tuple[str, ...]], level: int) -> None:
                    if level == len(grouping_columns) - 1:
                        ordered_combinations.extend(keys)
                        return
                    children: dict[str, list[tuple[str, ...]]] = {}
                    for key in keys:
                        children.setdefault(key[level], []).append(key)
                    for child_keys in children.values():
                        visit(child_keys, level + 1)

                visit(combinations, 0)
                combinations = ordered_combinations
        else:
            grouped_positions = {(): range(len(numeric))}
            combinations = [()]
        metric_values = numeric[candidate_metric].to_numpy()
        campaign_values = numeric["__cdf_campaign"].astype(str).to_numpy() if "__cdf_campaign" in numeric else None
        series_rows: list[tuple[tuple[object, ...], list[float], set[str]]] = []
        for combination in combinations:
            positions = grouped_positions.get(tuple(str(value) for value in combination))
            if positions is None:
                continue
            values = sorted(float(metric_values[position]) for position in positions)
            if values:
                campaigns = (
                    {str(campaign_values[position]) for position in positions}
                    if campaign_values is not None else set()
                )
                series_rows.append((combination, values, campaigns))
        if not series_rows:
            return None
        low = float(numeric[candidate_metric].min())
        observed_high = float(numeric[candidate_metric].max())
        automatic_high = _cdf_terminal_x_maximum([values for _key, values, _campaigns in series_rows], low, observed_high)
        automatic_high = automatic_high if automatic_high > low else low + 1
        (low, high), (y_low, y_high) = _cdf_domains(
            low, automatic_high, render_entry.axis_x_range, render_entry.axis_y_range,
        )
        colours = _series_colours(combinations, grouping_columns, numeric, line_chart=True)
        line_dashes = _series_line_dashes(combinations, grouping_columns, numeric)
        line_widths = _cdf_campaign_line_widths(
            [(combination, campaigns) for combination, _values, campaigns in series_rows],
            grouping_columns,
            numeric,
        )
        payload_series = []
        fallback_legend = []
        requested_legend = _legend_dimensions(render_entry.legend)
        for index, (combination, values, campaigns) in enumerate(series_rows):
            visible_points = _cdf_visible_points(values, low, high)
            if not visible_points:
                continue
            sampled = _interactive_sample(visible_points, INTERACTIVE_CHART_POINTS_PER_SERIES)
            line_width = line_widths.get(tuple(str(value) for value in combination), 4)
            full_label = _legend_key_caption(combination, grouping_columns, numeric, ())
            # A CDF legend and tooltip identify a concrete curve. Retaining
            # the full hierarchy prevents Operator-only captions when Vendor
            # is represented by its own multivendor aggregation level.
            tooltip_label = full_label
            colour = colours.get(combination, _colour(full_label, index))
            dash = line_dashes.get(combination, ())
            payload_series.append({
                "key": serialise_key(combination),
                "name": tooltip_label,
                "legend_name": full_label,
                "colour": colour,
                "width": line_width,
                "dash": list(dash),
                "x": [point[0] for _source_index, point in sampled],
                "y": [point[1] for _source_index, point in sampled],
                "samples": len(values),
            })
            fallback_legend.append((full_label, colour, line_width))
        model = _chart_payload_base(
            "cdf", candidate_title, render_entry, numeric, candidate_metric,
            fallback_legend, line_markers=True,
        )
        dash_by_label = {str(series["legend_name"]): list(series["dash"]) for series in payload_series}
        for legend_item in model.get("legend", {}).get("items", []):
            legend_item["dash"] = dash_by_label.get(str(legend_item.get("label", "")), [])
        model.update({
            "metric": candidate_metric.replace("_", " "),
            "domain": {"x": [low, high], "y": [y_low, y_high]},
            "series": payload_series,
        })
        return model

    if spec["kind"] == "multi_cdf":
        panels = []
        for candidate in spec.get("metrics", ()):
            resolved = _column(data, (candidate,)) or _catalog_column(data, candidate, multivendor)
            if resolved and (panel := cdf_model(resolved, candidate)):
                panels.append(panel)
        if not panels:
            return empty("No valid samples for this KPI and technology filter")
        return {
            # Each child CDF owns its legend. Resolving a second parent legend
            # repeats the expensive grouping over every source row, despite
            # that parent legend never being painted by drawMultiCdf.
            **_chart_payload_base("multi_cdf", title, render_entry, data, metric, show_legend=False),
            "panels": panels,
        }

    if chart_type == "cdf line":
        model = cdf_model(metric, title) if metric else None
        return model or empty("No valid samples for this KPI and technology filter")

    if spec["kind"] in {"status_100", "quality_100"} and metric:
        weight_column = "__catalog_weight" if "__catalog_weight" in data else None
        state_data = data[[
            group, period, metric, *hierarchy_columns,
            *([weight_column] if weight_column else []),
        ]].copy()
        state_data.attrs = data.attrs.copy()
        state_data, states, colours = _status_chart_categories(
            state_data, metric,
            quality=spec["kind"] == "quality_100",
            threshold=spec.get("threshold", 1.6),
            copy=False,
        )
        state_data = state_data.dropna(subset=[group, period])
        fallback = [
            (_legend_caption(_legend_labels(render_entry.legend), index, state), colour, 2)
            for index, (state, colour) in enumerate(zip(states, colours, strict=True))
        ]
        model = _chart_payload_base("status_100", title, render_entry, state_data, metric, fallback)
        model["domain"] = {
            "y": _configured_axis_domain(render_entry, "y", 0.0, 1.0, percentage=True),
        }
        model["states"] = [
            {
                "name": _legend_caption(_legend_labels(render_entry.legend), index, state),
                "colour": colour,
            }
            for index, (state, colour) in enumerate(zip(states, colours, strict=True))
        ]
        if column_hierarchy or row_hierarchy:
            render_columns = list(column_hierarchy)
            if not render_columns:
                state_data["__catalog_single_column"] = "(all)"
                render_columns = ["__catalog_single_column"]
            row_keys = _hierarchical_unique_keys(state_data, row_hierarchy) if row_hierarchy else [()]
            column_keys = _hierarchical_unique_keys(state_data, render_columns)
            dimensions = [*row_hierarchy, *render_columns]
            dimension_grouper = dimensions[0] if len(dimensions) == 1 else dimensions
            totals_group = state_data.groupby(
                dimension_grouper, sort=False, dropna=False, observed=True,
            )
            counts_group = state_data.groupby(
                [*dimensions, "state"], sort=False, dropna=False, observed=True,
            )
            totals = (
                totals_group[weight_column].sum() if weight_column
                else totals_group.size()
            )
            counts = (
                counts_group[weight_column].sum() if weight_column
                else counts_group.size()
            )

            def hierarchy_total(key: tuple[object, ...]) -> int:
                lookup = key[0] if len(dimensions) == 1 else key
                return int(totals.get(lookup, 0))

            cells = []
            for row_key in row_keys:
                row_cells = []
                for column_key in column_keys:
                    key = (*row_key, *column_key)
                    total = hierarchy_total(key)
                    row_cells.append(None if not total else [
                        float(counts.get((*key, state), 0)) / total for state in states
                    ])
                cells.append(row_cells)
            model.update({
                "mode": "hierarchy",
                "row_keys": [serialise_key(key) for key in row_keys],
                "column_keys": [serialise_key(key) for key in column_keys],
                "single_column": render_columns == ["__catalog_single_column"],
                "cells": cells,
            })
            return model
        combinations = list(state_data[[group, period]].drop_duplicates().itertuples(index=False, name=None))
        if weight_column:
            totals = state_data.groupby(
                [group, period], sort=False, dropna=False, observed=True,
            )[weight_column].sum()
            counts = state_data.groupby(
                [group, period, "state"], sort=False, dropna=False, observed=True,
            )[weight_column].sum()
        else:
            totals = state_data.groupby([group, period], sort=False, dropna=False).size()
            counts = state_data.groupby([group, period, "state"], sort=False, dropna=False).size()
        model.update({
            "mode": "flat",
            "categories": [_catalogue_display_label(*key) for key in combinations],
            "cells": [
                [
                    float(counts.get((*key, state), 0)) / max(int(totals.get(key, 0)), 1)
                    for state in states
                ]
                for key in combinations
            ],
        })
        return model

    if spec["kind"] == "failure_count":
        status = _column(data, ("Call_Status", "Test_Result", "status"))
        if not status:
            return empty("No failure status field is available")
        failed = data[data[status].astype(str).str.contains("failed|drop|cutoff", case=False, na=False)].copy()
        failed["__catalog_failure_state"] = failed[status].astype(str).map(
            lambda value: "Dropped" if "drop" in value.casefold() else "Failed"
        )
        state_colours = {"Failed": "#C83E4D", "Dropped": "#D8555F"}
        fallback = [
            (_legend_caption(_legend_labels(render_entry.legend), index, state), state_colours[state], 2)
            for index, state in enumerate(("Failed", "Dropped"))
        ]
        model = _chart_payload_base("failure_count", title, render_entry, data, metric, fallback)
        model["plot_legend_position"] = (
            parse_legend_position(render_entry.legend_position)
            if _legend_labels(render_entry.legend) else "none"
        )
        model["states"] = [
            {
                "name": _legend_caption(_legend_labels(render_entry.legend), index, state),
                "colour": state_colours[state],
            }
            for index, state in enumerate(("Failed", "Dropped"))
        ]
        if column_hierarchy or len(row_hierarchy) > 1:
            render_rows = row_hierarchy if column_hierarchy else []
            render_columns = column_hierarchy or row_hierarchy
            row_keys = _hierarchical_complete_keys(data, render_rows) if render_rows else [()]
            column_keys = _hierarchical_complete_keys(data, render_columns)
            counts = failed.groupby([*render_rows, *render_columns, "__catalog_failure_state"], dropna=False).size()
            levels = list(range(len(render_rows) + len(render_columns)))
            maximum = max(int(counts.groupby(level=levels).sum().max()), 1) if not counts.empty else 1
            cells = [
                [
                    [int(counts.get((*row_key, *column_key, state), 0)) for state in ("Failed", "Dropped")]
                    for column_key in column_keys
                ]
                for row_key in row_keys
            ]
            model.update({
                "mode": "hierarchy",
                "row_keys": [serialise_key(key) for key in row_keys],
                "column_keys": [serialise_key(key) for key in column_keys],
                "maximum": maximum,
                "domain": {
                    "x": _configured_axis_domain(render_entry, "x", 0.0, float(maximum)),
                },
                "cells": cells,
            })
            return model
        has_series = bool(period) and not data[period].fillna("(all)").astype(str).eq("(all)").all()
        fields = [group, period] if has_series else [group]
        counts = failed.groupby([*fields, "__catalog_failure_state"], dropna=False).size().unstack(fill_value=0)
        keys = _hierarchical_complete_keys(data, fields)
        comparison_index = (
            pd.Index([key[0] for key in keys], name=fields[0])
            if len(fields) == 1 else pd.MultiIndex.from_tuples(keys, names=fields)
        )
        counts = counts.reindex(comparison_index, fill_value=0).head(16)
        model.update({
            "mode": "flat",
            "maximum": max(int(counts.sum(axis=1).max()), 1) if not counts.empty else 1,
            "rows": [
                {
                    "key": serialise_key(label if isinstance(label, tuple) else (label,)),
                    "values": [int(values.get(state, 0)) for state in ("Failed", "Dropped")],
                }
                for label, values in counts.iterrows()
            ],
        })
        model["domain"] = {
            "x": _configured_axis_domain(
                render_entry, "x", 0.0, float(model["maximum"]),
            ),
        }
        return model

    if chart_type == "distribution stacked vertical bars" and "__catalog_stack" in data:
        axes = _chart_axis_hierarchy(data, distribution=True) or [group, period]
        distribution = data[[*axes, "__catalog_stack"]].dropna()
        distribution.attrs = data.attrs.copy()
        distribution = distribution[distribution["__catalog_stack"].astype(str).ne("(blank)")]
        distribution.attrs = data.attrs.copy()
        combinations = _hierarchical_unique_keys(distribution, axes)
        buckets = _distribution_buckets(distribution)
        if not combinations or not buckets:
            return empty("No valid samples for this KPI and technology filter")
        colours = _distribution_bucket_colours(buckets, distribution)
        counts = distribution.groupby([*axes, "__catalog_stack"], sort=False, dropna=False).size()
        axis_grouper = axes[0] if len(axes) == 1 else axes
        totals = distribution.groupby(axis_grouper, sort=False, dropna=False).size()

        def distribution_total(key: tuple[object, ...]) -> int:
            lookup = key[0] if len(axes) == 1 else key
            return int(totals.get(lookup, 0))

        legend_buckets = _distribution_buckets(distribution, legend=True)
        fallback = [
            (
                _legend_caption(_legend_labels(render_entry.legend), index, bucket),
                colours.get((bucket,), _colour(bucket, index)), 2,
            )
            for index, bucket in enumerate(legend_buckets)
        ]
        model = _chart_payload_base("distribution", title, render_entry, distribution, metric, fallback)
        model.update({
            "domain": {
                "y": _configured_axis_domain(render_entry, "y", 0.0, 1.0, percentage=True),
            },
            "axis_columns": axes,
            "keys": [serialise_key(key) for key in combinations],
            "buckets": [
                {
                    "name": _legend_caption(
                        _legend_labels(render_entry.legend), index, _chart_payload_value(bucket),
                    ),
                    "colour": colours.get((bucket,), _colour(bucket, index)),
                }
                for index, bucket in enumerate(buckets)
            ],
            "cells": [
                [
                    float(counts.get((*key, bucket), 0)) / max(distribution_total(key), 1)
                    for bucket in buckets
                ]
                for key in combinations
            ],
        })
        return model

    if spec["kind"] == "map" and metric:
        longitude = _column(data, spec.get("x_metric", ()))
        if not longitude:
            return empty("No coordinate or comparison field is available")
        columns = [metric, longitude, *([group] if group else []), *([period] if period and period != group else [])]
        points = data[columns].copy()
        points.attrs = data.attrs.copy()
        points[metric] = pd.to_numeric(points[metric], errors="coerce")
        points[longitude] = pd.to_numeric(points[longitude], errors="coerce")
        points = points.dropna(subset=[metric, longitude])
        if points.empty:
            return empty("No valid map coordinates are available")
        key_columns = [group, period] if period and group and period != group else [group] if group else []
        raw_keys = (
            [tuple(values) for values in points[key_columns].fillna("(blank)").astype(str).to_numpy()]
            if key_columns else [("All",)] * len(points)
        )
        unique_keys = list(dict.fromkeys(raw_keys))
        colours = _series_colours(unique_keys, key_columns, points)
        rows_by_key: dict[tuple[str, ...], list[tuple[float, float]]] = {
            key: [] for key in unique_keys
        }
        for key, longitude_value, latitude_value in zip(
            raw_keys, points[longitude], points[metric], strict=True,
        ):
            rows_by_key[key].append((float(longitude_value), float(latitude_value)))
        series_payload = []
        fallback = []
        for index, key in enumerate(unique_keys):
            rows = rows_by_key[key]
            sampled = _interactive_sample(rows, INTERACTIVE_SCATTER_POINTS_PER_SERIES)
            label = _legend_key_caption(key, key_columns, points, _legend_dimensions(render_entry.legend)) or " · ".join(key)
            colour = colours.get(key, _colour(key, index))
            series_payload.append({
                "name": label, "colour": colour,
                "points": [[longitude_value, latitude_value] for _source_index, (longitude_value, latitude_value) in sampled],
            })
            fallback.append((label, colour, 2))
        lon_low, lon_high = _configured_axis_domain(
            render_entry, "x", float(points[longitude].min()), float(points[longitude].max()),
        )
        lat_low, lat_high = _configured_axis_domain(
            render_entry, "y", float(points[metric].min()), float(points[metric].max()),
        )
        lon_padding = max((lon_high - lon_low) * .06, .004)
        lat_padding = max((lat_high - lat_low) * .06, .004)
        geometry = _osm_map_tile_geometry(
            lon_low - lon_padding, lon_high + lon_padding,
            lat_low - lat_padding, lat_high + lat_padding,
        )
        zoom, tile_left, tile_top, tile_right, tile_bottom, top_left, bottom_right = geometry
        return {
            **_chart_payload_base(
                "map", title, render_entry, data, metric,
                fallback,
            ),
            "x_label": longitude.replace("_", " "),
            "y_label": metric.replace("_", " "),
            "domain": {
                "x": [lon_low, lon_high],
                "y": [lat_low, lat_high],
            },
            "basemap": {
                "provider": "OpenStreetMap",
                "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "© OpenStreetMap contributors",
                "zoom": zoom,
                "tile_range": [tile_left, tile_top, tile_right, tile_bottom],
                "world_bounds": [*top_left, *bottom_right],
                "tile_size": OSM_TILE_SIZE,
            },
            "series": series_payload,
        }

    if chart_type in {"table", "dynamic table"} and metric:
        dynamic_table = chart_type == "dynamic table"
        aggregation = spec.get("aggregation")
        if dynamic_table and not aggregation:
            aggregation = "mean" if pd.to_numeric(data[metric], errors="coerce").notna().any() else "count"
        if aggregation:
            labels = data.attrs.get("catalogue_dimension_labels", {})
            metric_name = _normalise_catalog_name(metric)
            visible_columns = [
                column for column in column_hierarchy
                if _normalise_catalog_name(str(labels.get(column, column))) != metric_name
            ]
            column_dimension_names = {
                _normalise_catalog_name(str(labels.get(column, column)))
                for column in visible_columns
            }
            visible_rows = [
                column for column in row_hierarchy
                if _normalise_catalog_name(str(labels.get(column, column))) not in {
                    metric_name, *column_dimension_names,
                }
            ]
            if dynamic_table and visible_columns:
                pivot_width = len(data[visible_columns].drop_duplicates())
                if pivot_width > 20:
                    column_names = " × ".join(str(labels.get(column, column)) for column in visible_columns)
                    return empty(
                        f"Dynamic Table has {pivot_width} distinct column values for {column_names}. "
                        "Add a filter to reduce the table to 20 columns or fewer."
                    )
            dimensions = [*visible_rows, *visible_columns]
            aggregated = _aggregate_metric(data, dimensions, metric, aggregation)
            if aggregated.empty:
                return empty("No valid samples for this KPI and technology filter")

            def dimension_label(column: str) -> str:
                declared = labels.get(column, column)
                if isinstance(declared, (tuple, list)):
                    return " · ".join(str(item) for item in declared)
                return str(declared)

            def formatted(value: object) -> str:
                if pd.isna(value):
                    return ""
                if aggregation in {"count", "countd"}:
                    return f"{int(value):,}"
                return f"{float(value):.2f}"

            def dimension_sort_key(column: str, value: object) -> tuple[object, ...]:
                """Use Admin mapping order before the table's manual drag order."""
                declared = labels.get(column, column)
                declared_values = declared if isinstance(declared, (tuple, list)) else (declared,)
                roles = {
                    _normalise_catalog_name(str(item)) for item in declared_values
                }
                if roles & {"operator", "subscriber"}:
                    return (0, *_operator_display_sort_key(value, data))
                if roles & {"vendor", "vendoronly", "operatorvendor"}:
                    if multivendor:
                        return (0, *_multivendor_vendor_sort_key(value, data))
                    return (0, *_vendor_display_sort_key(value, data))
                if "campaign" in roles:
                    return (0, *_campaign_sort_key(value))
                return (1, str(value).casefold())

            def hierarchy_sort_key(
                columns: list[str], values: tuple[object, ...],
            ) -> tuple[tuple[object, ...], ...]:
                return tuple(
                    dimension_sort_key(column, value)
                    for column, value in zip(columns, values, strict=True)
                )

            if visible_columns:
                table = aggregated.unstack(visible_columns)
                column_keys = [
                    value if isinstance(value, tuple) else (value,)
                    for value in table.columns
                ]
                column_names = [
                    " · ".join(str(item) for item in value)
                    for value in column_keys
                ]
                column_order = sorted(
                    range(len(column_keys)),
                    key=lambda index: hierarchy_sort_key(visible_columns, column_keys[index]),
                )
                table = table.iloc[:, column_order]
                column_keys = [column_keys[index] for index in column_order]
                column_names = [column_names[index] for index in column_order]
                headers = [*[dimension_label(column) for column in visible_rows], *column_names]
                rows = []
                for index, values in table.iterrows():
                    index_values = index if isinstance(index, tuple) else (index,)
                    rows.append([*[_chart_payload_value(value) for value in index_values], *[formatted(value) for value in values]])
            else:
                headers = [*[dimension_label(column) for column in visible_rows], f"{aggregation.upper()}({metric})"]
                rows = []
                for index, value in aggregated.items():
                    index_values = index if isinstance(index, tuple) else (index,)
                    rows.append([*[_chart_payload_value(item) for item in index_values], formatted(value)])
            if dynamic_table:
                rows.sort(key=lambda row: hierarchy_sort_key(
                    visible_rows, tuple(row[:len(visible_rows)]),
                ))
            rows = rows[:36 if dynamic_table else 18]
            return {
                **_chart_payload_base("table", title, render_entry, data, metric),
                "aggregation": aggregation,
                "dynamic": dynamic_table,
                "row_dimension_count": len(visible_rows),
                "column_keys": [serialise_key(key) for key in column_keys] if visible_columns else [],
                "column_heading": " · ".join(dimension_label(column) for column in visible_columns),
                "headers": headers,
                "rows": rows,
            }
        table_data = data[[group, period, metric]].copy() if period else data[[group, metric]].copy()
        numeric_metric = pd.to_numeric(table_data[metric], errors="coerce")
        has_series = bool(period) and not table_data[period].fillna("(all)").astype(str).eq("(all)").all()
        suffix = ""
        if numeric_metric.notna().any():
            table_data[metric] = numeric_metric
            table_data = table_data.dropna(subset=[metric])
            if "percentile" in title.casefold():
                table = table_data.groupby(group, sort=False)[metric].quantile([.1, .5, .9]).unstack()
                table.columns = ["P10", "P50", "P90"]
            elif has_series:
                table = table_data.pivot_table(index=group, columns=period, values=metric, aggfunc="mean", sort=False)
            else:
                table = table_data.groupby(group, sort=False)[metric].mean().to_frame("Value")
        else:
            categorical = table_data.dropna(subset=[group, metric]).copy()
            if categorical.empty:
                return empty("No valid samples for this KPI and technology filter")
            columns = [period, metric] if has_series else [metric]
            table = pd.crosstab(categorical[group], [categorical[column] for column in columns], normalize="index") * 100
            suffix = "%"
        headers = [str(table.index.name or "Category"), *[str(value) for value in table.columns]]
        rows = [
            [str(index), *["" if pd.isna(value) else f"{float(value):.2f}{suffix}" for value in values]]
            for index, values in table.head(18).iterrows()
        ]
        return {
            **_chart_payload_base("table", title, render_entry, data, metric),
            "headers": headers,
            "rows": rows,
        }

    if metric and "vertical bars" in chart_type:
        axes = _chart_axis_hierarchy(data) or ([group, period] if period and period != group else [group])
        values = data[[*axes, metric]].copy()
        values.attrs = data.attrs.copy()
        aggregation = spec.get("aggregation") or ("median" if chart_type == "median vertical bars" else "mean")
        means = _aggregate_metric(values, axes, metric, aggregation)
        if means.empty:
            return empty("No valid samples for this KPI and technology filter")
        # A column-only hierarchy still needs the matrix model. Rendering it
        # as a flat sequence preserves source append order (for example every
        # operator for Q1, then every operator for Q2) instead of nesting all
        # campaigns beneath their operator.
        if column_hierarchy or row_hierarchy:
            render_columns = column_hierarchy or ["__catalog_single_column"]
            if render_columns == ["__catalog_single_column"]:
                values["__catalog_single_column"] = "(all)"
                means = _aggregate_metric(values, [*row_hierarchy, *render_columns], metric, aggregation)
            row_keys = _hierarchical_unique_keys(values, row_hierarchy) if row_hierarchy else [()]
            column_keys = _hierarchical_unique_keys(values, render_columns)
            lookup = {key if len(axes) > 1 else key[0]: float(value) for key, value in means.items()}
            flat_keys = [label if isinstance(label, tuple) else (label,) for label in means.index]
            colours = _series_colours(flat_keys, [*row_hierarchy, *render_columns], values)
            def mean_value(row_key: tuple[object, ...], column_key: tuple[object, ...]) -> float | None:
                key = (*row_key, *column_key)
                lookup_key = key if len(key) > 1 else key[0]
                return lookup.get(lookup_key)
            def mean_colour(row_key: tuple[object, ...], column_key: tuple[object, ...]) -> str:
                key = (*row_key, *column_key)
                return colours.get(key, _colour(key))
            return {
                **_chart_payload_base("mean_bar", title, render_entry, values, metric),
                "mode": "hierarchy",
                "metric": metric.replace("_", " "),
                "aggregation": aggregation,
                "maximum": max(float(means.max()), 1.0),
                "domain": {
                    "y": _configured_axis_domain(
                        render_entry, "y", min(0.0, float(means.min())), max(float(means.max()), 1.0),
                    ),
                },
                "row_keys": [serialise_key(key) for key in row_keys],
                "column_keys": [serialise_key(key) for key in column_keys],
                "cells": [[mean_value(row_key, column_key) for column_key in column_keys] for row_key in row_keys],
                "cell_colours": [[mean_colour(row_key, column_key) for column_key in column_keys] for row_key in row_keys],
                # Retain the flat values for existing API consumers. Canvas
                # rendering uses the explicit row/column matrix above.
                "bars": [
                    {
                        "key": serialise_key(key), "value": float(value),
                        "colour": colours.get(key, _colour(key, item_index)),
                        "legend": _legend_key_caption(key, [*row_hierarchy, *render_columns], values, _legend_dimensions(render_entry.legend)),
                    }
                    for item_index, (key, value) in enumerate(zip(flat_keys, means.tolist(), strict=True))
                ],
            }
        keys = [label if isinstance(label, tuple) else (label,) for label in means.index]
        colours = _series_colours(keys, axes, values)
        return {
            **_chart_payload_base("mean_bar", title, render_entry, values, metric),
            "metric": metric.replace("_", " "),
            "aggregation": aggregation,
            "axis_columns": axes,
            "maximum": max(float(means.max()), 1.0),
            "domain": {
                "y": _configured_axis_domain(
                    render_entry, "y", min(0.0, float(means.min())), max(float(means.max()), 1.0),
                ),
            },
            "bars": [
                {
                    "key": serialise_key(key),
                    "value": float(value),
                    "colour": colours.get(key, _colour(key, index)),
                    "legend": _legend_key_caption(key, axes, values, _legend_dimensions(render_entry.legend)),
                }
                for index, (key, value) in enumerate(zip(keys, means.tolist(), strict=True))
            ],
        }

    if spec["kind"] == "scatter" and metric:
        x_metric = _column(data, spec.get("x_metric", ()))
        if not x_metric:
            return empty("No coordinate or comparison field is available")
        data["__catalog_label"] = [
            _catalogue_display_label(category, series)
            for category, series in data[[group, period]].fillna("(blank)").itertuples(index=False, name=None)
        ]
        points = data[["__catalog_label", metric, x_metric]].copy()
        points.attrs = data.attrs.copy()
        points[metric] = pd.to_numeric(points[metric], errors="coerce")
        points[x_metric] = pd.to_numeric(points[x_metric], errors="coerce")
        points = points.dropna()
        if points.empty:
            return empty("No valid samples for this KPI and technology filter")
        keys = [(str(label),) for label in points["__catalog_label"].drop_duplicates().tolist()]
        colours = _series_colours(keys, ["__catalog_label"], points)
        payload_series = []
        fallback = []
        for index, (label, subset) in enumerate(points.groupby("__catalog_label", sort=False)):
            rows = list(subset[[x_metric, metric]].itertuples(index=False, name=None))
            sampled = _interactive_sample(rows, INTERACTIVE_SCATTER_POINTS_PER_SERIES)
            colour = colours.get((str(label),), _colour(label, index))
            payload_series.append({
                "name": str(label), "colour": colour,
                "points": [[float(x), float(y)] for _source_index, (x, y) in sampled],
            })
            fallback.append((label, colour, 2))
        return {
            **_chart_payload_base("scatter", title, render_entry, data, metric, fallback),
            "x_label": x_metric.replace("_", " "),
            "y_label": metric.replace("_", " "),
            "domain": {
                "x": _configured_axis_domain(
                    render_entry, "x", float(points[x_metric].min()), float(points[x_metric].max()),
                ),
                "y": _configured_axis_domain(
                    render_entry, "y", float(points[metric].min()), float(points[metric].max()),
                ),
            },
            "series": payload_series,
        }

    if spec["kind"] == "cdf_mean":
        model = cdf_model(metric, title) if metric else None
        return model or empty("No valid samples for this KPI and technology filter")

    return empty("Select a valid KPI for the selected CDR type to render this chart preview")


def _chart_for_catalog_entry(
    entry: CatalogEntry,
    frames: dict[str, pd.DataFrame],
    multivendor: bool,
    *,
    prefiltered: bool = False,
) -> BytesIO:
    spec = _catalog_spec(entry)
    chart_title = entry.chart_title or entry.slide_title
    legend_dimensions = _legend_dimensions(entry.legend)
    legend_labels = _legend_labels(entry.legend)
    legend_position = parse_legend_position(entry.legend_position)
    # Slash-separated captions are retained for old templates. All current
    # field-based legends are resolved centrally after rendering, so the
    # renderer cannot substitute its own states/buckets/series.
    renderer_legend_position = legend_position if legend_labels else "none"
    if prefiltered:
        frame = frames[spec["source"]].copy()
        group = period = None
    else:
        frame, group, period = _source_for_spec(frames, spec, multivendor)
    frame.attrs["catalogue_calculated_dimensions"] = entry.calculated_dimensions
    frame.attrs["catalogue_cdr_source"] = entry.cdr_source
    metric = _metric_column(frame, spec)
    try:
        if not prefiltered:
            frame = _apply_catalog_filters(frame, entry, multivendor, metric)
        frame = _exclude_chart_values(frame, entry, spec, multivendor)
        frame, group, period = _apply_catalog_grouping(frame, entry, multivendor, metric)
    except ValueError:
        # A partial CDR upload should leave only the affected chart empty, not fail the report.
        return _empty_chart(chart_title)
    chart_type = entry.chart_type.casefold()
    if chart_type != "distribution stacked vertical bars" and "__catalog_stack" in frame.columns:
        frame[period] = frame[period].astype(str) + " · " + frame["__catalog_stack"].astype(str)
    def finish(chart: BytesIO) -> BytesIO:
        return chart if legend_labels else _apply_resolved_legend(chart, entry, frame, metric, legend_position)
    if spec["kind"] == "status_100":
        return finish(_render_status_100(chart_title, frame, group, period, metric=metric, legend_labels=legend_labels, legend_position=renderer_legend_position, label_position=entry.label_position))
    if spec["kind"] == "quality_100":
        return finish(_render_status_100(chart_title, frame, group, period, True, spec.get("threshold", 1.6), metric, legend_labels, renderer_legend_position, entry.label_position))
    if spec["kind"] == "failure_count":
        return finish(_render_failure_count(chart_title, frame, group, period, legend_labels, renderer_legend_position, entry.label_position))
    if spec["kind"] == "map":
        return finish(_render_map(chart_title, frame, group, period, metric, _column(frame, spec.get("x_metric", ())), legend_labels, renderer_legend_position))
    if spec["kind"] == "multi_cdf":
        charts = []
        for candidate in spec.get("metrics", ()):
            resolved = _column(frame, (candidate,)) or _catalog_column(frame, candidate, multivendor)
            if resolved:
                charts.append(_render_cdf_line(
                    candidate, frame, group, period, resolved, legend_dimensions,
                    renderer_legend_position, layout_legend_position=legend_position,
                    axis_x_range=entry.axis_x_range, axis_y_range=entry.axis_y_range,
                    exclude_null_empty=entry.exclude_null_empty, exclude_zero=entry.exclude_zero,
                ))
        return _combine_charts(chart_title, charts) if charts else _empty_chart(chart_title)
    if chart_type == "distribution stacked vertical bars":
        return finish(_render_stacked_distribution(chart_title, frame, group, period, "__catalog_stack", legend_labels, renderer_legend_position, entry.label_position))
    # Non-stacked visuals have one visual series per row/column combination. A
    # rows-only chart remains a single category series rather than becoming the
    # misleading ``Operator · Operator`` label used by the earlier renderer.
    frame["__catalog_label"] = [
        _catalogue_display_label(category, series)
        for category, series in frame[[group, period]].fillna("(blank)").itertuples(index=False, name=None)
    ]
    if spec["kind"] == "scatter":
        return finish(_render_scatter(chart_title, frame, "__catalog_label", metric, _column(frame, spec.get("x_metric", ())), (), renderer_legend_position))
    if chart_type in {"table", "dynamic table"}:
        return finish(_render_table(
            chart_title, frame, group, period, metric,
            percentiles="percentile" in chart_title.casefold(),
            aggregation=spec.get("aggregation"),
        ))
    if "vertical bars" in chart_type:
        return finish(_render_mean_column(
            chart_title, frame, group, period, metric,
            aggregation=spec.get("aggregation") or ("median" if chart_type == "median vertical bars" else "mean"),
            legend_dimensions=() if not legend_labels else legend_dimensions,
            legend_position=renderer_legend_position,
            label_position=entry.label_position,
        ))
    return finish(_render_cdf_line(
        chart_title, frame, group, period, metric, (), renderer_legend_position,
        layout_legend_position=legend_position,
        axis_x_range=entry.axis_x_range, axis_y_range=entry.axis_y_range,
        exclude_null_empty=entry.exclude_null_empty, exclude_zero=entry.exclude_zero,
    ))


def _chart_for_spec(title: str, frames: dict[str, pd.DataFrame], spec: dict, multivendor: bool) -> BytesIO:
    frame, group, period = _source_for_spec(frames, spec, multivendor); metric = _metric_column(frame, spec)
    if spec["kind"] == "status_100": return _render_status_100(title, frame, group, period, metric=metric)
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
            _render_cdf_line("POLQA AVG MOS CDF", frame, group, period, metric),
        ])
    if spec["kind"] == "cdf_pair":
        secondary_metric = _column(frame, spec.get("secondary_metric", ()))
        return _combine_charts(title, [
            _render_cdf_line(metric.replace("_", " ") if metric else title, frame, group, period, metric),
            _render_cdf_line(secondary_metric.replace("_", " ") if secondary_metric else title, frame, group, period, secondary_metric),
        ])
    if spec["kind"] == "cdf_bucket":
        # The template combines a throughput CDF with a low-rate distribution.
        # The averaged columns are retained as the numerical distribution summary.
        return _render_cdf_line(title, frame, group, period, metric)
    return _render_cdf_line(title, frame, group, period, metric)


def _clear_commentary(slide) -> None:
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        if getattr(shape, "is_placeholder", False) and shape.placeholder_format.idx == 10:
            shape.text_frame.clear()
            continue
        text = shape.text.strip().lower()
        if len(text) > 45 and any(hint in text for hint in COMMENT_HINTS):
            shape.text_frame.clear()


def _set_commentary(slide, comments: list[str] | tuple[str, ...]) -> None:
    """Write saved Dashboard notes into the layout's commentary placeholder."""
    values = [str(comment).strip() for comment in comments if str(comment).strip()]
    if not values:
        return
    placeholder = next(
        (
            shape for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
            and getattr(shape, "is_placeholder", False)
            and shape.placeholder_format.idx == 10
        ),
        None,
    )
    if placeholder is None:
        return
    text_frame = placeholder.text_frame
    text_frame.clear()
    for index, value in enumerate(values):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        paragraph.text = value
        paragraph.level = 0


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
    if title_shape is not None and (title or subtitle):
        # The template title placeholder is the single header surface. Keep the
        # template subtitle inside it as a second paragraph rather than adding
        # a separate text box below the placeholder.
        text_frame = title_shape.text_frame
        text_frame.clear()
        title_paragraph = text_frame.paragraphs[0]
        title_paragraph.text = title
        if subtitle:
            subtitle_paragraph = text_frame.add_paragraph()
            subtitle_paragraph.text = subtitle
            subtitle_paragraph.font.size = Pt(16)
            subtitle_paragraph.font.color.rgb = RGBColor(36, 90, 150)
    existing_subtitle = next((shape for shape in slide.shapes if shape.name == "catalogue-subtitle"), None)
    if existing_subtitle is not None:
        existing_subtitle._element.getparent().remove(existing_subtitle._element)


def _set_structural_slide_text(slide, title: str, subtitle: str) -> None:
    """Populate a title/transition layout without creating extra text boxes."""
    title_shape = next(
        (
            shape for shape in slide.placeholders
            if shape.placeholder_format.type in {1, 3}
        ),
        None,
    )
    subtitle_shape = next(
        (
            shape for shape in slide.placeholders
            if shape.placeholder_format.type == 4
        ),
        None,
    )
    if title_shape is not None:
        title_shape.text = title
        title_shape.text_frame.word_wrap = True
        title_shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    if subtitle_shape is not None:
        subtitle_shape.text = subtitle
        subtitle_shape.text_frame.word_wrap = True
        subtitle_shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    elif subtitle:
        _set_slide_header(slide, title, subtitle)

    # Structural slides keep only their title/subtitle placeholders. Branding
    # and decorations inherited from the master/layout remain untouched.
    retained_elements = {
        shape._element for shape in (title_shape, subtitle_shape) if shape is not None
    }
    for shape in list(slide.placeholders):
        if shape._element in retained_elements:
            continue
        shape._element.getparent().remove(shape._element)


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


def _remove_template_chart_placeholders(slide) -> None:
    """Remove inherited chart pictures stored *inside* the template placeholders.

    The supplied templates encode their sample Tableau exports as picture
    placeholders rather than regular picture shapes.  Removing only regular
    images therefore left the old chart under the new one.  Index 0 is the
    master title and index 10 is the deliberately blank analyst-comments area.
    """
    for shape in list(slide.shapes):
        if not getattr(shape, "is_placeholder", False):
            continue
        if shape.placeholder_format.idx in {0, 10}:
            continue
        shape._element.getparent().remove(shape._element)


def _combined_frame(frames: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not frames:
        return None
    left = min(frame[0] for frame in frames)
    top = min(frame[1] for frame in frames)
    right = max(frame[0] + frame[2] for frame in frames)
    bottom = max(frame[1] + frame[3] for frame in frames)
    return left, top, right - left, bottom - top


def _named_slide_layout(presentation: Presentation, layout_name: str):
    """Resolve a template layout name against the template slide master."""
    expected = layout_name.strip().casefold()
    for layout in presentation.slide_layouts:
        if layout.name.strip().casefold() == expected:
            return layout
    return None


def _remove_all_slides(presentation: Presentation) -> None:
    """Leave the source deck as a master/layout-only presentation."""
    slide_id_list = presentation.slides._sldIdLst
    for slide_id in list(slide_id_list):
        presentation.part.drop_rel(slide_id.rId)
        slide_id_list.remove(slide_id)


def _apply_catalogue_layout(presentation: Presentation, slide, layout_name: str):
    """Assign the requested layout and align retained structural placeholders."""
    layout = _named_slide_layout(presentation, layout_name)
    if layout is None:
        return None
    layout_relationship_ids = [
        relationship_id
        for relationship_id, relationship in slide.part.rels.items()
        if relationship.reltype == RT.SLIDE_LAYOUT
    ]
    for relationship_id in layout_relationship_ids:
        slide.part.rels.pop(relationship_id)
    slide.part.rels.get_or_add(RT.SLIDE_LAYOUT, layout.part)

    layout_placeholders = {
        placeholder.placeholder_format.idx: placeholder
        for placeholder in layout.placeholders
    }
    for shape in slide.placeholders:
        target = layout_placeholders.get(shape.placeholder_format.idx)
        if target is None or shape.placeholder_format.idx not in {0, 10}:
            continue
        shape.left, shape.top = target.left, target.top
        shape.width, shape.height = target.width, target.height
    return layout


def _layout_chart_frames(layout) -> list[tuple[int, int, int, int]]:
    """Read chart placeholder frames from the selected template layout."""
    if layout is None:
        return []
    frames = [
        (shape.left, shape.top, shape.width, shape.height)
        for shape in layout.placeholders
        if shape.placeholder_format.type == 7 and shape.placeholder_format.idx != 10
    ]
    # PowerPoint layouts commonly differ by one or two EMU between placeholders
    # that are visually on the same row. A strict (top, left) sort therefore
    # placed the right-hand chart before the left-hand chart. Build visual rows
    # with a small vertical tolerance, then order each row from left to right.
    visual_rows: list[list[tuple[int, int, int, int]]] = []
    row_tolerance = int(Inches(0.08))
    for frame in sorted(frames, key=lambda item: item[1]):
        matching_row = next(
            (row for row in visual_rows if abs(frame[1] - min(item[1] for item in row)) <= row_tolerance),
            None,
        )
        if matching_row is None:
            visual_rows.append([frame])
        else:
            matching_row.append(frame)
    visual_rows.sort(key=lambda row: min(frame[1] for frame in row))
    return [frame for row in visual_rows for frame in sorted(row, key=lambda item: item[0])]


def render_cdr_report(destination: Path, template: Path, frames: dict[str, pd.DataFrame] | None, technology: str,
                      multivendor: bool, catalog: list[CatalogEntry] | None = None,
                      chart_output_dir: Path | None = None,
                      frame_loader: Callable[[str], pd.DataFrame] | None = None,
                      on_chart_rendered: Callable[[CatalogEntry, int, bool], None] | None = None,
                      generate_tooltips: bool = True, reuse_existing_charts: bool = False) -> Path:
    if not template.exists():
        raise FileNotFoundError(f"Reporting template not found: {template.name}")
    if not catalog:
        raise ValueError("A Report Template is required to generate the report.")
    # A report may concatenate campaigns that were exported using different
    # operator spellings.  Apply aliases only to these in-memory report frames
    # before filtering and grouping; Workspace datasets remain source-faithful.
    if frames is None and frame_loader is None:
        raise ValueError('Report rendering requires CDR frames or a frame loader.')
    # Keep only the source currently needed when a loader is supplied.  This
    # avoids retaining Data, Voice and Speech frames simultaneously for large
    # reports on resource-constrained servers.
    cached_frames = {source: normalise_operator_aliases(frame) for source, frame in (frames or {}).items()}
    active_source: str | None = None
    def frame_for(source: str) -> pd.DataFrame:
        nonlocal active_source
        # Keep at most one lazy-loaded CDR frame resident.  The catalogue
        # order still determines slide/chart order, while switching sources
        # releases the previous large DataFrame before loading the next one.
        if frame_loader is not None and source != active_source:
            cached_frames.clear()
            prepared_frames.clear()
            gc.collect()
        if source not in cached_frames:
            if frame_loader is None:
                raise ValueError(f'No CDR frame is available for {source}.')
            cached_frames[source] = normalise_operator_aliases(frame_loader(source))
        active_source = source
        return cached_frames[source]
    presentation = Presentation(template)
    _remove_all_slides(presentation)
    rendered_charts: list[dict[str, object]] = []
    prepared_frames: dict[tuple[object, ...], pd.DataFrame] = {}
    selected_renderer = report_chart_renderer_name()

    def prepared_chart_frame(source_frame: pd.DataFrame, entry: CatalogEntry) -> tuple[pd.DataFrame, CatalogEntry]:
        prepared_entry = prepare_multivendor_catalog_entry(entry) if multivendor else entry
        key = (
            id(source_frame), prepared_entry.source_kind, prepared_entry.cdr_source,
            prepared_entry.kpi, prepared_entry.filters, prepared_entry.calculated_dimensions,
        )
        prepared = prepared_frames.get(key)
        if prepared is None:
            try:
                prepared = prepare_catalog_chart_preview_frame(
                    source_frame, prepared_entry, multivendor=False,
                )[0]
            except ValueError:
                # Historical templates can reference a field absent from one
                # selected CDR. Preserve the established empty-chart result.
                prepared = source_frame.iloc[0:0].copy()
            prepared_frames[key] = prepared
        return prepared, prepared_entry

    catalogue_slides: dict[int, list[CatalogEntry]] = defaultdict(list)
    render_catalog = [prepare_multivendor_catalog_entry(entry) if multivendor else entry for entry in catalog]
    for entry in render_catalog:
        catalogue_slides[entry.slide].append(entry)

    expected_chart_files = set()
    if chart_output_dir is not None:
        for number, entries in catalogue_slides.items():
            automated = [entry for entry in entries if entry.source_kind]
            expected_chart_files.update(
                f'slide-{number:03d}-chart-{index:02d}.png'
                for index, _entry in enumerate(automated, start=1)
            )
        chart_output_dir.mkdir(parents=True, exist_ok=True)
        # A cancelled worker can leave a half-written image or assets from an
        # older template. Keep only deterministic chart names; each candidate
        # is verified again when it is consumed below.
        for child in chart_output_dir.iterdir():
            if child.name == 'manifest.json' or child.name.removesuffix('.hover.json') + '.png' not in expected_chart_files and child.name not in expected_chart_files:
                child.unlink(missing_ok=True)
    hover_executor = (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='report-hover')
        if generate_tooltips and selected_renderer == 'pil' else None
    )
    for number in sorted(catalogue_slides):
        slide_entries = catalogue_slides[number]
        header = slide_entries[0]
        structural = header.structural_type
        if not structural and header.chart_type.strip().casefold() in PRESERVED_CHART_TYPES:
                structural = "title slide" if number == min(catalogue_slides) else "transition slide"

        if structural:
            layout_name = header.layout or ("Title Page" if structural == "title slide" else "Title Only")
            layout = _named_slide_layout(presentation, layout_name)
            if layout is None:
                raise ValueError(f"Slide {number}: layout '{layout_name}' does not exist in the selected template.")
            slide = presentation.slides.add_slide(layout)
            _set_structural_slide_text(slide, header.slide_title, header.slide_subtitle)
            continue

        chart_entries = [entry for entry in slide_entries if entry.source_kind]
        if not chart_entries:
            raise ValueError(
                f"Slide {number} does not define an automated chart, a Title Slide or a Transition Slide."
            )
        layouts = {entry.layout for entry in chart_entries}
        if len(layouts) != 1:
            raise ValueError(f"Slide {number} uses more than one Layout in the active template.")
        layout_name = layouts.pop()
        layout = _named_slide_layout(presentation, layout_name)
        if layout is None:
            raise ValueError(f"Slide {number}: layout '{layout_name}' does not exist in the selected template.")
        placement_frames = _layout_chart_frames(layout)
        if len(placement_frames) < len(chart_entries):
            raise ValueError(
                f"Slide {number}: layout '{layout_name}' has {len(placement_frames)} chart placeholders, "
                f"but the template defines {len(chart_entries)} charts."
            )
        slide = presentation.slides.add_slide(layout)
        _set_slide_header(slide, header.slide_title, header.slide_subtitle)
        _clear_commentary(slide)
        _remove_template_chart_placeholders(slide)
        for chart_index, (entry, placement) in enumerate(zip(chart_entries, placement_frames[:len(chart_entries)], strict=True), start=1):
            # The PowerPoint must consume the exact same renderer used by the
            # editor and Report Charts.  Keeping this call shared prevents an
            # unnoticed drift in normalisation, multivendor preparation or
            # catalogue filtering between preview and export.
            file_name = f'slide-{number:03d}-chart-{chart_index:02d}.png'
            hover_file = f'slide-{number:03d}-chart-{chart_index:02d}.hover.json'
            chart_path = chart_output_dir / file_name if chart_output_dir is not None else None
            chart_bytes = None
            if reuse_existing_charts and chart_path and chart_path.is_file():
                try:
                    with Image.open(chart_path) as existing:
                        existing.verify()
                    chart_bytes = chart_path.read_bytes()
                except (OSError, ValueError, SyntaxError):
                    chart_path.unlink(missing_ok=True)
            source_frame = frame_for(entry.source_kind)
            source_unavailable = bool(source_frame.attrs.get("report_source_unavailable"))
            prepared_frame, prepared_entry = (
                (source_frame, entry) if source_unavailable else prepared_chart_frame(source_frame, entry)
            )
            reusable_hover = None
            if chart_bytes is not None and generate_tooltips and chart_output_dir is not None:
                try:
                    reusable_hover = json.loads((chart_output_dir / hover_file).read_text(encoding='utf-8'))
                    if not isinstance(reusable_hover, list):
                        reusable_hover = None
                except (OSError, json.JSONDecodeError):
                    reusable_hover = None
            hover_future = hover_executor.submit(
                catalog_chart_hover_targets, prepared_frame, prepared_entry, prefiltered=True,
            ) if hover_executor and not source_unavailable and reusable_hover is None else None
            canvas_hover = None
            if chart_bytes is None:
                if source_unavailable:
                    chart_bytes = render_unavailable_source_chart(entry)
                elif selected_renderer == 'dashboard-canvas':
                    chart_bytes, canvas_hover = render_catalog_chart_preview_with_hover(
                        prepared_frame, prepared_entry, prefiltered=True, renderer=selected_renderer,
                    )
                else:
                    chart_bytes = render_catalog_chart_preview(
                        prepared_frame, prepared_entry, prefiltered=True, renderer=selected_renderer,
                    )
            # Rebuild the source frame before retrying an unexpected empty
            # chart. Retrying the same already-loaded frame cannot recover a
            # worker that was under memory pressure while materialising it.
            for _attempt in range(2):
                if source_unavailable or not is_empty_catalog_chart(chart_bytes, entry) or frame_loader is None:
                    break
                del chart_bytes
                cached_frames.pop(entry.source_kind, None)
                prepared_frames.clear()
                gc.collect()
                source_frame = frame_for(entry.source_kind)
                prepared_frame, prepared_entry = prepared_chart_frame(source_frame, entry)
                if selected_renderer == 'dashboard-canvas':
                    chart_bytes, canvas_hover = render_catalog_chart_preview_with_hover(
                        prepared_frame, prepared_entry, prefiltered=True, renderer=selected_renderer,
                    )
                else:
                    chart_bytes = render_catalog_chart_preview(
                        prepared_frame, prepared_entry, prefiltered=True, renderer=selected_renderer,
                    )
            if reusable_hover is not None:
                hover_targets = reusable_hover
            elif generate_tooltips and canvas_hover is not None:
                hover_targets = canvas_hover
            elif hover_future:
                hover_targets = hover_future.result()
            elif generate_tooltips and chart_bytes is not None and selected_renderer == 'dashboard-canvas' and not source_unavailable:
                # A reused PNG without a matching sidecar cannot expose its in-memory Canvas hits.
                hover_targets = catalog_chart_hover_targets(prepared_frame, prepared_entry, prefiltered=True)
            else:
                hover_targets = None
            if on_chart_rendered:
                on_chart_rendered(entry, len(source_frame.index), is_empty_catalog_chart(chart_bytes, entry))
            if chart_output_dir is not None:
                (chart_output_dir / file_name).write_bytes(chart_bytes)
                rendered_charts.append({
                    'slide': number,
                    'title': entry.chart_title or entry.slide_title or f'Slide {number}',
                    'source': entry.cdr_source,
                    'chart_type': entry.chart_type,
                    'file': file_name,
                })
                if isinstance(hover_targets, list):
                    (chart_output_dir / hover_file).write_text(json.dumps(hover_targets, ensure_ascii=False), encoding='utf-8')
                    rendered_charts[-1]['hover_file'] = hover_file
            slide.shapes.add_picture(BytesIO(chart_bytes), *placement)
    if hover_executor:
        hover_executor.shutdown(wait=True)
    cached_frames.clear()
    gc.collect()
    presentation.save(destination)
    if chart_output_dir is not None:
        (chart_output_dir / 'manifest.json').write_text(
            json.dumps({
                'generate_tooltips': generate_tooltips,
                'hover_targets_version': HOVER_TARGETS_VERSION,
                'charts': rendered_charts,
            }),
            encoding='utf-8',
        )
    return destination
