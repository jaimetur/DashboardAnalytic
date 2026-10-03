"""Canonical report layout names shared by storage, imports and rendering."""
from __future__ import annotations

import csv
import io
import re

DYNAMIC_LAYOUTS = (
    "Title + 2 rows + dynamic columns",
    "Title + dynamic rows + 2 columns",
    "Title + 2 rows + dynamic columns + comments right",
    "Title + 2 rows + dynamic columns + comments down",
    "Title + dynamic rows + 2 columns + comments right",
    "Title + dynamic rows + 2 columns + comments down",
)


def grid_layout_name(rows: int, columns: int, comments: str = "") -> str:
    return f"Title + {rows} rows + {columns} columns" + (f" + comments {comments}" if comments else "")


def canonical_layout_name(value: str) -> str:
    """Translate historic grid names without changing internal structural layouts."""
    name = value.strip()
    dynamic = re.fullmatch(r"(?:Title\s*\+\s*)?(2 rows \+ dynamic columns|2 columns \+ dynamic rows|dynamic rows \+ 2 columns)(?:(?:,| \+) comments (down|right))?", name, re.I)
    if dynamic:
        direction, comments = dynamic.groups()
        return f"Title + {'2 rows + dynamic columns' if direction.lower().startswith('2 rows') else 'dynamic rows + 2 columns'}" + (f" + comments {comments.lower()}" if comments else "")
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
    return value in {'Title Page', 'Title Only', *DYNAMIC_LAYOUTS} or bool(re.fullmatch(
        r"Title \+ [1-9]\d* rows \+ [1-9]\d* columns(?: \+ comments (?:down|right))?", value,
    ))


def normalize_catalog_layouts(content: bytes) -> bytes:
    """Change only Layout cells, retaining the template's columns and other values."""
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
