"""Canonical report layout names shared by storage, imports and rendering."""
from __future__ import annotations

import csv
import io
import re

DYNAMIC_LAYOUTS = tuple(
    f"Title + {axes}" + (f" + comments {comments}" if comments else "")
    for axes in ('2 rows + dynamic columns', 'dynamic rows + 2 columns', 'dynamic rows + dynamic columns')
    for comments in ('', 'down', 'right')
)


def dynamic_layout_axes(layout: str) -> tuple[bool, bool]:
    canonical = canonical_layout_name(layout).lower()
    return 'dynamic rows' in canonical, 'dynamic columns' in canonical


def grid_layout_name(rows: int, columns: int, comments: str = "") -> str:
    return f"Title + {rows} rows + {columns} columns" + (f" + comments {comments}" if comments else "")


def canonical_layout_name(value: str) -> str:
    """Translate historic grid names without changing internal structural layouts."""
    name = value.strip()
    dynamic = re.fullmatch(r"(?:Title\s*\+\s*)?(2 rows \+ dynamic columns|2 columns \+ dynamic rows|dynamic rows \+ 2 columns|dynamic rows \+ dynamic columns)(?:(?:,| \+) comments (down|right))?", name, re.I)
    if dynamic:
        direction, comments = dynamic.groups()
        direction = direction.lower()
        axes = direction if direction != "2 columns + dynamic rows" else "dynamic rows + 2 columns"
        return f"Title + {axes}" + (f" + comments {comments.lower()}" if comments else "")
    canonical = re.fullmatch(r"Title \+ (\d+) rows \+ (\d+) columns(?: \+ comments (down|right))?", name, re.I)
    if canonical:
        rows, columns, comments = canonical.groups()
        return grid_layout_name(int(rows), int(columns), (comments or "").lower())
    old = re.fullmatch(r"Title and (\d+) (rows?|columns?)(?: and (\d+) (rows?|columns?))?(?: \((.*?)\))?(?: \+ Comments(?: (down|right))?)?", name, re.I)
    if old:
        first, direction, second, other, variant, comments = old.groups()
        rows, columns = (int(first), 1) if direction.lower().startswith('row') else (1, int(first))
        if second:
            if other.lower().startswith('row'):
                rows = int(second)
            else:
                columns = int(second)
        if variant and 'rows' in variant.lower():
            rows = 2
        return grid_layout_name(rows, columns, (comments or 'down').lower() if '+ comments' in name.lower() else '')
    return name


def selectable_layout_name(value: str) -> bool:
    return value in {'Title Page', 'Title Only', 'Transition', 'Black logo end slide', *DYNAMIC_LAYOUTS} or bool(re.fullmatch(
        r"Title \+ [1-9]\d* rows \+ [1-9]\d* columns(?: \+ comments (?:down|right))?", value,
    ))


def normalize_catalog_layouts(content: bytes) -> bytes:
    """Normalize layout names and extend recognized template schemas without losing values."""
    try:
        text = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        if 'Layout' not in headers:
            return content
        rows = list(reader)
        if any(None in row for row in rows):
            return content
        changed = False
        for legacy in ('CDR source', 'CDR Source'):
            if legacy in headers:
                headers[headers.index(legacy)] = 'Source Dataset'
                for row in rows:
                    row['Source Dataset'] = row.pop(legacy)
                changed = True
        base_headers = ['Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout', 'Chart Tittle', 'Source Dataset', 'KPI', 'Chart type', 'Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend', 'Legend Position']
        optional_headers = ['Legend Format', 'Label Position', 'Label Format', 'Axis X Range', 'Axis Y Range', 'Exclude Null/Empty', 'Exclude Zero', 'Dynamic Rows Field', 'Dynamic Columns Field']
        if 'Dynamic Field' in headers:
            position = headers.index('Dynamic Field')
            headers[position:position + 1] = ['Dynamic Rows Field', 'Dynamic Columns Field']
            for row in rows:
                legacy = row.pop('Dynamic Field') or ''
                dynamic_rows, dynamic_columns = dynamic_layout_axes(row.get('Layout') or '')
                row['Dynamic Rows Field'] = legacy if dynamic_rows else ''
                row['Dynamic Columns Field'] = legacy if dynamic_columns else ''
            changed = True
        non_dynamic_headers = [header for header in headers if header not in {'Dynamic Rows Field', 'Dynamic Columns Field'}]
        if set(base_headers).issubset(non_dynamic_headers) and all(header in base_headers + optional_headers for header in headers):
            complete_headers = base_headers[:4] + ['Dynamic Rows Field', 'Dynamic Columns Field'] + base_headers[4:] + optional_headers[:-2]
            if headers != complete_headers:
                headers = complete_headers
                for row in rows:
                    for header in optional_headers:
                        row.setdefault(header, '')
                changed = True
        for row in rows:
            old = row.get('Layout') or ''
            new = canonical_layout_name(old)
            if old != new:
                row['Layout'] = new
                changed = True
        if not changed:
            return content
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode('utf-8')
    except (UnicodeDecodeError, csv.Error):
        return content
