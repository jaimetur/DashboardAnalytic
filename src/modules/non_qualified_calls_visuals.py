"""Non-Qualified Calls report panels drawn like the page: KPI cards, breakdown bars, donuts, timeline and workload.

Each panel is a PNG that fills the content area of a slide (and a landscape Word page), so PowerPoint and Word
show the Executive Summary and the Progress View with the look of the web page.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from src.utils.fonts import load_image_font

DPI = 200
PANEL_WIDTH = 12.28
PANEL_HEIGHT = 4.75
DARK = '#7d1238'
TEXT = '#3d1824'
MUTED = '#8a6b76'
BORDER = '#f0c4d3'
TRACK = '#f3dfe6'
RASPBERRY = '#b0234f'
PALETTE = ['#b0234f', '#0f6f7d', '#e08a1e', '#6a63c9', '#2e8b57', '#245a96', '#b85b20', '#7b8790', '#5b6b2e', '#c8365f']
KPI_COLORS = {'total': '#b0234f', 'open': '#d14a68', 'closed': '#2e8b57', 'team': '#0f6f7d', 'commented': '#6a63c9'}
SERVICE_LABELS = {'voice': 'Voice', 'speech': 'Speech', 'data': 'Data'}


def _px(inches: float) -> int:
    return round(inches * DPI)


def _font(points: float, bold: bool = False):
    return load_image_font(max(1, round(points * DPI / 72)), bold=bold)


def _number(value: Any) -> str:
    return f'{int(value or 0):,}'


def _share(count: int, total: int) -> str:
    return f'{count * 100 / total:.0f}%' if total else '0%'


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    """Shorten a label with an ellipsis so it never runs into the next element."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text.rstrip() + '…'


class Panel:
    """A white canvas in inches; cards are placed with inch coordinates."""

    def __init__(self, width: float = PANEL_WIDTH, height: float = PANEL_HEIGHT) -> None:
        self.width, self.height = width, height
        self.image = Image.new('RGB', (_px(width), _px(height)), 'white')
        self.draw = ImageDraw.Draw(self.image)

    def card(self, left: float, top: float, width: float, height: float, accent: str | None = None) -> None:
        box = [_px(left), _px(top), _px(left + width), _px(top + height)]
        self.draw.rounded_rectangle(box, radius=_px(0.12), fill='white', outline=BORDER, width=max(2, _px(0.012)))
        if accent:
            self.draw.rounded_rectangle([box[0], box[1], box[2], box[1] + _px(0.07)], radius=_px(0.035), fill=accent)

    def text(self, left: float, top: float, value: str, points: float, *, bold: bool = False, color: str = TEXT,
             width: float | None = None, anchor: str = 'la') -> None:
        font = _font(points, bold)
        if width is not None:
            value = _fit(self.draw, value, font, _px(width))
        self.draw.text((_px(left), _px(top)), value, font=font, fill=color, anchor=anchor)

    def png(self) -> BytesIO:
        output = BytesIO()
        self.image.save(output, 'PNG', dpi=(DPI, DPI))
        output.seek(0)
        return output


def _kpi_row(panel: Panel, cards: list[tuple[str, str, str, str]], top: float, height: float) -> None:
    gap = 0.18
    width = (panel.width - gap * (len(cards) - 1)) / len(cards)
    for index, (label, value, note, kind) in enumerate(cards):
        left = index * (width + gap)
        panel.card(left, top, width, height, KPI_COLORS.get(kind, RASPBERRY))
        panel.text(left + 0.16, top + 0.2, label.upper(), 8.5, bold=True, color=MUTED, width=width - 0.3)
        panel.text(left + 0.16, top + 0.42, value, 22, bold=True, color=DARK, width=width - 0.3)
        panel.text(left + 0.16, top + height - 0.3, note, 8.5, color=MUTED, width=width - 0.3)


def _bar_card(panel: Panel, left: float, top: float, width: float, height: float, title: str,
              items: list[tuple[str, int, str]], *, label_above: bool = False) -> None:
    """A breakdown card: a bar per value, longest first, as in the Executive Summary of the page."""
    panel.card(left, top, width, height)
    panel.text(left + 0.18, top + 0.16, title, 12, bold=True, color=DARK, width=width - 0.36)
    row = 0.42 if label_above else 0.3
    rows = max(1, int((height - 0.6) / row))
    shown = items[:rows]
    if not shown:
        panel.text(left + 0.18, top + 0.6, 'No calls.', 9, color=MUTED)
        return
    maximum = max(1, *(count for _label, count, _color in shown))
    label_width = 0 if label_above else min(1.6, width * 0.38)
    count_width = 0.6
    for index, (label, count, color) in enumerate(shown):
        y = top + 0.58 + index * row
        track_left = left + 0.18 + label_width + (0 if label_above else 0.1)
        track_width = width - 0.36 - label_width - (0 if label_above else 0.1) - count_width
        if label_above:
            panel.text(left + 0.18, y - 0.08, label, 8.5, bold=True, color=TEXT, width=width - 0.36)
            y += 0.16
        else:
            panel.text(left + 0.18, y, label, 9, bold=True, color=TEXT, width=label_width, anchor='lm')
        bar_top, bar_bottom = _px(y - 0.06), _px(y + 0.06)
        panel.draw.rounded_rectangle([_px(track_left), bar_top, _px(track_left + track_width), bar_bottom], radius=_px(0.06), fill=TRACK)
        fill = max(0.05, track_width * count / maximum)
        panel.draw.rounded_rectangle([_px(track_left), bar_top, _px(track_left + fill), bar_bottom], radius=_px(0.06), fill=color or RASPBERRY)
        panel.text(left + width - 0.18, y, _number(count), 9, bold=True, color=DARK, anchor='rm')


def _donut_card(panel: Panel, left: float, top: float, width: float, height: float, title: str,
                items: list[tuple[str, int, str]]) -> None:
    """A donut with the total in its centre and a legend with each value's count and share."""
    panel.card(left, top, width, height)
    panel.text(left + 0.16, top + 0.14, title, 11, bold=True, color=DARK, width=width - 0.3)
    total = sum(count for _label, count, _color in items)
    # The donut sits under the title and its legend below it, using the whole width of the card.
    size = min(width - 0.6, (height - 0.55) * 0.5)
    cx, cy = left + width / 2, top + 0.5 + size / 2
    box = [_px(cx - size / 2), _px(cy - size / 2), _px(cx + size / 2), _px(cy + size / 2)]
    thickness = _px(size * 0.17)
    panel.draw.ellipse(box, outline=TRACK, width=thickness)
    start = -90.0
    for _label, count, color in items:
        if not total or not count:
            continue
        sweep = count / total * 360
        panel.draw.arc(box, start, start + sweep + 0.4, fill=color, width=thickness)
        start += sweep
    panel.text(cx, cy, _number(total), 13, bold=True, color=DARK, anchor='mm')
    legend_top = top + 0.62 + size
    row = 0.24
    shown = items[:max(1, int((top + height - 0.1 - legend_top) / row))]
    for index, (label, count, color) in enumerate(shown):
        y = legend_top + index * row
        panel.draw.rounded_rectangle([_px(left + 0.16), _px(y - 0.06), _px(left + 0.28), _px(y + 0.06)], radius=_px(0.03), fill=color)
        value = f'{_number(count)} · {_share(count, total)}'
        value_width = panel.draw.textlength(value, font=_font(8)) / DPI
        panel.text(left + 0.36, y, label, 8.5, bold=True, color=TEXT, width=width - 0.62 - value_width, anchor='lm')
        panel.text(left + width - 0.16, y, value, 8, color=MUTED, anchor='rm')

def _items(distribution: dict[str, Any], colours: dict[tuple[str, str], str]) -> list[tuple[str, int, str]]:
    field = distribution.get('field') or ''
    empty = 'Unassigned' if field in {'team', 'assignee'} else 'Not classified'
    items = []
    for index, item in enumerate(distribution.get('items') or []):
        value = str(item.get('value') or '')
        label = item.get('label') or (SERVICE_LABELS.get(value, value) if field == 'service' else value) or empty
        colour = item.get('color') or colours.get((field, value)) or PALETTE[index % len(PALETTE)]
        items.append((str(label), int(item.get('count') or 0), colour))
    return items


def _option_colours(options: dict[str, Any]) -> dict[tuple[str, str], str]:
    colours = {('status', item['name']): item['color'] for item in options.get('statuses') or [] if item.get('color')}
    colours.update({('team', item['name']): item['color'] for item in options.get('teams') or [] if item.get('color')})
    return colours


def executive_summary_panels(summary: dict[str, Any], breakdowns: list[dict[str, Any]], options: dict[str, Any]) -> list[tuple[str, BytesIO]]:
    """The Executive Summary: the indicator cards with the first breakdowns, then the other breakdowns three at a time."""
    total = int(summary.get('total') or 0)
    colours = _option_colours(options)
    cards = [
        ('Non-Qualified Calls', _number(total), 'Calls and tests that did not complete', 'total'),
        ('Open', _number(summary.get('open')), f"{_share(summary.get('open') or 0, total)} still under follow-up", 'open'),
        ('Closed', _number(summary.get('closed')), f"{_share(summary.get('closed') or 0, total)} resolved or not applicable", 'closed'),
        ('With Team', _number(summary.get('with_team')), f"{_share(summary.get('with_team') or 0, total)} have a responsible team", 'team'),
        ('Commented', _number(summary.get('commented')), f"{_share(summary.get('commented') or 0, total)} have comments", 'commented'),
    ]
    regular = [breakdown for breakdown in breakdowns if breakdown.get('field') != 'dataset_id']
    wide = [breakdown for breakdown in breakdowns if breakdown.get('field') == 'dataset_id']
    panels = []
    first = Panel()
    _kpi_row(first, cards, 0, 1.25)
    _bar_row(first, regular[:3], colours, 1.45, first.height - 1.45)
    panels.append(('Executive Summary', first.png()))
    rest = regular[3:]
    for index in range(0, len(rest), 3):
        panel = Panel()
        _bar_row(panel, rest[index:index + 3], colours, 0, panel.height)
        pages = (len(rest) + 2) // 3
        panels.append(('Executive Summary · Breakdowns' + (f' · {index // 3 + 1}/{pages}' if pages > 1 else ''), panel.png()))
    for breakdown in wide:
        panel = Panel()
        _bar_card(panel, 0, 0, panel.width, panel.height, breakdown['label'], _items(breakdown, colours), label_above=True)
        panels.append((f"Executive Summary · {breakdown['label'].removeprefix('By ')}", panel.png()))
    return panels


def _bar_row(panel: Panel, breakdowns: list[dict[str, Any]], colours: dict[tuple[str, str], str], top: float, height: float) -> None:
    if not breakdowns:
        return
    gap = 0.18
    width = (panel.width - gap * 2) / 3
    for index, breakdown in enumerate(breakdowns):
        _bar_card(panel, index * (width + gap), top, width, height, breakdown['label'], _items(breakdown, colours))


def _days(value: Any) -> str:
    return '—' if value is None else f'{float(value):.1f} d'


def progress_view_panels(progress: dict[str, Any], options: dict[str, Any], granularity_label: str) -> list[tuple[str, BytesIO]]:
    """The Progress View: indicator cards and donuts, the timeline, then age and workload."""
    summary = progress.get('summary') or {}
    total = int(summary.get('total') or 0)
    colours = _option_colours(options)
    cards = [
        ('Attended', _number(summary.get('attended')), f"{_share(summary.get('attended') or 0, total)} have a follow-up", 'open'),
        ('Not Attended', _number(summary.get('not_attended')), 'No change or comment yet', 'total'),
        ('Closure Rate', f"{float(summary.get('closure_rate') or 0):.1f}%", f"{_number(summary.get('closed'))} of {_number(total)} closed", 'closed'),
        ('First Follow-up', _days(summary.get('avg_days_to_first_follow_up')), 'Average from the call', 'team'),
        ('Time to Close', _days(summary.get('avg_days_to_close')), 'Average from the first follow-up', 'commented'),
        ('Activity', _number((summary.get('comments') or 0) + (summary.get('changes') or 0)),
         f"{_number(summary.get('comments'))} comments · {_number(summary.get('changes'))} changes", ''),
    ]
    panels = []
    first = Panel()
    _kpi_row(first, cards, 0, 1.25)
    distributions = progress.get('distributions') or []
    gap = 0.18
    width = (first.width - gap * (len(distributions) - 1)) / max(1, len(distributions))
    for index, distribution in enumerate(distributions):
        _donut_card(first, index * (width + gap), 1.45, width, first.height - 1.45, distribution['label'], _items(distribution, colours))
    panels.append(('Progress View', first.png()))
    timeline = _timeline_panel(progress.get('periods') or [], granularity_label)
    if timeline is not None:
        panels.append((f'Progress View · Progress per {granularity_label}', timeline))
    work = Panel()
    third = (work.width - gap * 2) / 3
    _bar_card(work, 0, 0, third, work.height, 'Age of Open Calls',
              [(str(item['value']), int(item['count']), RASPBERRY) for item in progress.get('aging') or []])
    _workload_card(work, third + gap, 0, third, work.height, 'Team Workload', progress.get('teams') or [])
    _workload_card(work, 2 * (third + gap), 0, third, work.height, 'Assignee Workload', progress.get('assignees') or [])
    panels.append(('Progress View · Age and Workload', work.png()))
    return panels


def _workload_card(panel: Panel, left: float, top: float, width: float, height: float, title: str, rows: list[dict[str, Any]]) -> None:
    """Open and closed calls per team or assignee as stacked bars."""
    panel.card(left, top, width, height)
    panel.text(left + 0.18, top + 0.16, title, 12, bold=True, color=DARK)
    legend_x = left + width - 0.18
    for label, colour in (('Closed', '#2e8b57'), ('Open', RASPBERRY)):
        text_width = panel.draw.textlength(label, font=_font(8)) / DPI
        panel.text(legend_x, top + 0.2, label, 8, color=MUTED, anchor='ra')
        legend_x -= text_width + 0.05
        panel.draw.rounded_rectangle([_px(legend_x - 0.12), _px(top + 0.21), _px(legend_x), _px(top + 0.33)], radius=_px(0.03), fill=colour)
        legend_x -= 0.25
    shown = rows[:max(1, int((height - 0.6) / 0.3))]
    if not shown:
        panel.text(left + 0.18, top + 0.6, 'No calls.', 9, color=MUTED)
        return
    maximum = max(1, *(int(row['total']) for row in shown))
    label_width = min(1.4, width * 0.36)
    track_left = left + 0.28 + label_width
    track_width = width - 0.46 - label_width - 0.75
    for index, row in enumerate(shown):
        y = top + 0.62 + index * 0.3
        panel.text(left + 0.18, y, str(row['name']), 9, bold=True, color=TEXT, width=label_width, anchor='lm')
        open_width = track_width * int(row['open']) / maximum
        closed_width = track_width * int(row['closed']) / maximum
        bar_top, bar_bottom = _px(y - 0.06), _px(y + 0.06)
        panel.draw.rounded_rectangle([_px(track_left), bar_top, _px(track_left + track_width), bar_bottom], radius=_px(0.06), fill=TRACK)
        if open_width:
            panel.draw.rounded_rectangle([_px(track_left), bar_top, _px(track_left + max(open_width, 0.05)), bar_bottom], radius=_px(0.06), fill=RASPBERRY)
        if closed_width:
            start = track_left + open_width
            panel.draw.rounded_rectangle([_px(start), bar_top, _px(start + max(closed_width, 0.05)), bar_bottom], radius=_px(0.06), fill='#2e8b57')
        panel.text(left + width - 0.18, y, f"{_number(row['open'])} / {_number(row['closed'])}", 8.5, bold=True, color=DARK, anchor='rm')


def _timeline_panel(periods: list[dict[str, Any]], granularity_label: str) -> BytesIO | None:
    """Detected, attended and closed calls per period as bars, with the open backlog as a line, like the page."""
    shown = periods[-24:]
    if not shown:
        return None
    panel = Panel()
    panel.card(0, 0, panel.width, panel.height)
    panel.text(0.2, 0.16, f'Progress per {granularity_label}', 12, bold=True, color=DARK)
    series = [('detected', 'Detected', '#8a6b76'), ('attended', 'Attended', '#e08a1e'), ('closed', 'Closed', '#2e8b57')]
    legend_x = 3.2
    for _key, label, colour in [*series, ('open_backlog', 'Open backlog', '#b0234f')]:
        panel.draw.rounded_rectangle([_px(legend_x), _px(0.22), _px(legend_x + 0.14), _px(0.36)], radius=_px(0.03), fill=colour)
        panel.text(legend_x + 0.2, 0.2, label, 9, color=TEXT)
        legend_x += 0.4 + panel.draw.textlength(label, font=_font(9)) / DPI
    left, right, top, bottom = 0.75, panel.width - 0.25, 0.65, panel.height - 0.5
    maximum = max(1, *(max(int(period.get(key) or 0) for key, _label, _colour in series) for period in shown),
                  *(int(period.get('open_backlog') or 0) for period in shown))
    step = 10 ** max(0, int(math.log10(maximum)) - 1)
    maximum = math.ceil(maximum / step / 4) * step * 4 if maximum > 4 else 4
    for share in (0, 0.25, 0.5, 0.75, 1):
        y = bottom - (bottom - top) * share
        panel.draw.line([_px(left), _px(y), _px(right), _px(y)], fill='#efe3e8', width=2)
        panel.text(left - 0.08, y, _number(round(maximum * share)), 8, color=MUTED, anchor='rm')
    slot = (right - left) / len(shown)
    bar = min(0.22, (slot - 0.1) / len(series))
    points = []
    for index, period in enumerate(shown):
        start = left + index * slot + (slot - bar * len(series)) / 2
        for position, (key, _label, colour) in enumerate(series):
            value = int(period.get(key) or 0)
            height = (bottom - top) * value / maximum
            if height > 0:
                x = start + position * bar
                panel.draw.rounded_rectangle([_px(x), _px(bottom - height), _px(x + bar - 0.03), _px(bottom)], radius=_px(0.02), fill=colour)
        centre = left + index * slot + slot / 2
        points.append((_px(centre), _px(bottom - (bottom - top) * int(period.get('open_backlog') or 0) / maximum)))
        panel.text(centre, bottom + 0.1, str(period.get('period') or ''), 8, color=MUTED, anchor='ma', width=max(0.5, slot))
    if len(points) > 1:
        panel.draw.line(points, fill='#b0234f', width=_px(0.03), joint='curve')
    for x, y in points:
        radius = _px(0.04)
        panel.draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill='#b0234f', outline='white', width=2)
    return panel.png()


def table_panels(title: str, columns: list[str], rows: list[list[str]], rows_per_panel: int = 13) -> list[tuple[str, BytesIO]]:
    """A detail table drawn like the page's tables: raspberry header, alternate rows and muted zeros."""
    pages = [rows[index:index + rows_per_panel] for index in range(0, len(rows), rows_per_panel)] or [[]]
    panels = []
    for number, page in enumerate(pages, start=1):
        # The card is as tall as its rows, so a short table does not leave an empty slide-sized card.
        panel = Panel(height=min(PANEL_HEIGHT, 0.6 + 0.3 * (max(1, len(page)) + 1) + 0.2))
        panel.card(0, 0, panel.width, panel.height)
        panel.text(0.2, 0.16, title.split(' · ', 1)[-1], 12, bold=True, color=DARK)
        left, right, top = 0.2, panel.width - 0.2, 0.6
        header_font, body_font = _font(8.5, True), _font(8.5)
        widths = []
        for index, column in enumerate(columns):
            longest = max([panel.draw.textlength(column, font=header_font),
                           *(panel.draw.textlength(str(row[index]), font=body_font) for row in page)]) / DPI
            widths.append(longest + 0.24)
        scale = (right - left) / max(sum(widths), 0.1)
        widths = [width * scale for width in widths]
        row_height = min(0.3, (panel.height - top - 0.15) / (len(page) + 1))
        panel.draw.rounded_rectangle([_px(left), _px(top), _px(right), _px(top + row_height)], radius=_px(0.06), fill='#fcedf2')
        x = left
        for index, column in enumerate(columns):
            numeric = index > 0
            anchor = 'rm' if numeric else 'lm'
            panel.text(x + widths[index] - 0.12 if numeric else x + 0.12, top + row_height / 2, column, 8.5,
                       bold=True, color=DARK, width=widths[index] - 0.18, anchor=anchor)
            x += widths[index]
        if not page:
            panel.text(left + 0.12, top + row_height * 1.6, 'No data for this selection.', 9, color=MUTED, anchor='lm')
        for row_index, row in enumerate(page):
            y = top + row_height * (row_index + 1)
            if row_index % 2:
                panel.draw.rectangle([_px(left), _px(y), _px(right), _px(y + row_height)], fill='#fff7fa')
            panel.draw.line([_px(left), _px(y + row_height), _px(right), _px(y + row_height)], fill='#f6e3ea', width=2)
            x = left
            for index, value in enumerate(row):
                text = str(value)
                muted = text in {'0', '—', ''}
                numeric = index > 0
                panel.text(x + widths[index] - 0.12 if numeric else x + 0.12, y + row_height / 2, text, 8.5,
                           bold=not numeric, color=MUTED if muted else TEXT, width=widths[index] - 0.18,
                           anchor='rm' if numeric else 'lm')
                x += widths[index]
        panels.append((title + (f' · {number}/{len(pages)}' if len(pages) > 1 else ''), panel.png()))
    return panels
