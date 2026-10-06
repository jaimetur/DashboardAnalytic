"""Word versions of the PowerPoint reports: each slide becomes a landscape page with the same content.

Slide titles become headings, tables become Word tables with their colours, native charts are drawn as
images from their data, and pictures and text boxes are copied in reading order.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from src.utils.fonts import load_image_font

EMU_PER_INCH = 914400
CHART_PALETTE = ['#245a96', '#e08a1e', '#2e8b57', '#b0234f', '#6a63c9', '#0f6f7d', '#b85b20', '#7b8790']
TITLE_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}


def _colour(fill: Any) -> str | None:
    """The solid fill colour of a cell or series as #RRGGBB, when it has one."""
    try:
        if fill.type is not None and fill.fore_color and fill.fore_color.type is not None:
            return f'#{fill.fore_color.rgb}'
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _foreground(hex_colour: str | None) -> str:
    if not hex_colour:
        return '#17232D'
    red, green, blue = (int(hex_colour[index:index + 2], 16) for index in (1, 3, 5))
    return '#FFFFFF' if red * 0.299 + green * 0.587 + blue * 0.114 < 150 else '#17232D'


def _shade(cell: Any, hex_colour: str) -> None:
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), hex_colour.lstrip('#'))
    cell._tc.get_or_add_tcPr().append(shading)


def _copy_table(document: Document, source: Any, scale: float) -> None:
    rows, columns = len(source.rows), len(source.columns)
    table = document.add_table(rows=rows, cols=columns)
    table.style = 'Table Grid'
    table.autofit = False
    for index, column in enumerate(source.columns):
        table.columns[index].width = int(column.width * scale)
    for row_index, row in enumerate(source.rows):
        for column_index in range(columns):
            origin = source.cell(row_index, column_index)
            target = table.cell(row_index, column_index)
            target.width = int(source.columns[column_index].width * scale)
            text = ' '.join(origin.text.splitlines())
            fill = _colour(origin.fill)
            if fill:
                _shade(target, fill)
            paragraph = target.paragraphs[0]
            paragraph.paragraph_format.space_before = paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(text)
            run.font.size = Pt(8)
            run.font.name = 'Arial'
            first = next((item for item in origin.text_frame.paragraphs[0].runs), None) if origin.text_frame.paragraphs else None
            run.bold = bool(first and first.font.bold) or row_index == 0
            try:
                colour = first.font.color.rgb if first is not None and first.font.color and first.font.color.type is not None else None
            except AttributeError:
                colour = None
            run.font.color.rgb = RGBColor.from_string(str(colour)) if colour else RGBColor.from_string(_foreground(fill).lstrip('#'))


def _chart_image(chart: Any, width_in: float, height_in: float) -> BytesIO | None:
    """A clustered bar chart drawn from the chart's own categories, series values and colours."""
    try:
        plot = chart.plots[0]
        categories = [str(category) for category in plot.categories]
        series = [(item.name, [float(value or 0) for value in item.values], _colour(item.format.fill)) for item in plot.series]
    except (IndexError, AttributeError, TypeError, ValueError):
        return None
    if not categories or not series:
        return None
    dpi = 150
    width, height = int(width_in * dpi), int(height_in * dpi)
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    font, small = load_image_font(int(9 * dpi / 72)), load_image_font(int(7.5 * dpi / 72))
    left, right, top, bottom = int(0.6 * dpi), width - int(0.2 * dpi), int(0.45 * dpi), height - int(0.55 * dpi)
    values = [value for _name, numbers, _colour_value in series for value in numbers]
    low, high = min(0.0, *values), max(0.0, *values)
    if high == low:
        high = low + 1
    zero = bottom - (0 - low) / (high - low) * (bottom - top)
    for share in (0, 0.25, 0.5, 0.75, 1):
        y = bottom - share * (bottom - top)
        draw.line([left, y, right, y], fill='#e6eaef', width=1)
        draw.text((left - 6, y), f'{low + (high - low) * share:,.1f}', font=small, fill='#5b6377', anchor='rm')
    slot = (right - left) / len(categories)
    bar = max(2.0, min(slot * 0.8 / len(series), 0.35 * dpi))
    for index, category in enumerate(categories):
        start = left + index * slot + (slot - bar * len(series)) / 2
        for position, (_name, numbers, colour) in enumerate(series):
            value = numbers[index] if index < len(numbers) else 0
            y = bottom - (value - low) / (high - low) * (bottom - top)
            x = start + position * bar
            draw.rectangle([x, min(y, zero), x + bar - 1, max(y, zero)], fill=colour or CHART_PALETTE[position % len(CHART_PALETTE)])
        label = category if draw.textlength(category, font=small) <= slot else category[:max(1, int(len(category) * slot / max(1, draw.textlength(category, font=small))) - 1)] + '…'
        draw.text((left + index * slot + slot / 2, bottom + 6), label, font=small, fill='#3d4656', anchor='ma')
    x = left
    for position, (name, _numbers, colour) in enumerate(series):
        draw.rectangle([x, int(0.12 * dpi), x + 12, int(0.12 * dpi) + 12], fill=colour or CHART_PALETTE[position % len(CHART_PALETTE)])
        draw.text((x + 18, int(0.12 * dpi) - 2), str(name), font=font, fill='#17232D')
        x += 30 + draw.textlength(str(name), font=font)
    output = BytesIO()
    image.save(output, 'PNG')
    output.seek(0)
    return output


def _slide_title(slide: Any) -> tuple[str, Any]:
    for shape in slide.placeholders:
        if shape.placeholder_format.type in TITLE_TYPES and shape.has_text_frame and shape.text_frame.text.strip():
            return ' '.join(shape.text_frame.text.split()), shape
    return '', None


def _soffice() -> str | None:
    """LibreOffice, from the environment, the PATH or its usual macOS location."""
    candidates = [os.environ.get('DRIVETEST_ANALYZER_SOFFICE', ''), shutil.which('soffice') or '', shutil.which('libreoffice') or '',
                  '/Applications/LibreOffice.app/Contents/MacOS/soffice']
    return next((path for path in candidates if path and Path(path).is_file() and os.access(path, os.X_OK)), None)


def slide_images(content: bytes, dpi: int = 160) -> list[bytes] | None:
    """Every slide as a PNG, rendered by LibreOffice through PDF, or None when LibreOffice is unavailable."""
    soffice = _soffice()
    try:
        import pymupdf
    except ImportError:
        return None
    if soffice is None:
        return None
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'report.pptx'
        source.write_bytes(content)
        # A private profile lets the conversion run while the user has LibreOffice open.
        profile = (Path(folder) / 'profile').as_uri()
        try:
            subprocess.run([soffice, f'-env:UserInstallation={profile}', '--headless', '--convert-to', 'pdf',
                            '--outdir', folder, str(source)], check=True, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            return None
        pdf = Path(folder) / 'report.pdf'
        if not pdf.is_file():
            return None
        with pymupdf.open(pdf) as document:
            return [page.get_pixmap(dpi=dpi).tobytes('png') for page in document]


def pptx_to_docx(content: bytes, title: str = '') -> bytes:
    """Convert a generated PowerPoint into a landscape Word document with one page per slide.

    With LibreOffice, every page shows the slide exactly as in PowerPoint (layout, colours, tables and charts);
    without it, the slide content is rebuilt: headings, tables with their colours and charts drawn from their data.
    """
    images = slide_images(content)
    if images:
        document = Document()
        section = document.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Inches(11.69), Inches(8.27)
        section.left_margin = section.right_margin = Inches(0.5)
        section.top_margin = section.bottom_margin = Inches(0.5)
        usable_width = (section.page_width - section.left_margin - section.right_margin) / EMU_PER_INCH
        usable_height = (section.page_height - section.top_margin - section.bottom_margin) / EMU_PER_INCH - 0.3
        for index, image in enumerate(images):
            with Image.open(BytesIO(image)) as raster:
                ratio = raster.width / raster.height
            width = min(usable_width, usable_height * ratio)
            paragraph = document.paragraphs[0] if index == 0 and document.paragraphs else document.add_paragraph()
            paragraph.alignment = 1
            paragraph.paragraph_format.page_break_before = index > 0
            paragraph.add_run().add_picture(BytesIO(image), width=Inches(width))
        output = BytesIO()
        document.save(output)
        return output.getvalue()
    presentation = Presentation(BytesIO(content))
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11.69), Inches(8.27)
    section.left_margin = section.right_margin = Inches(0.6)
    section.top_margin = section.bottom_margin = Inches(0.6)
    usable = (section.page_width - section.left_margin - section.right_margin) / EMU_PER_INCH
    scale = usable / (presentation.slide_width / EMU_PER_INCH)
    if title:
        document.add_heading(title, level=0)
    first_content = True
    for slide in presentation.slides:
        heading_text, title_shape = _slide_title(slide)
        shapes = sorted((shape for shape in slide.shapes if shape is not title_shape),
                        key=lambda shape: (round((shape.top or 0) / (EMU_PER_INCH * 0.25)), shape.left or 0))
        body = [shape for shape in shapes if shape.has_table or getattr(shape, 'has_chart', False)
                or shape.shape_type == MSO_SHAPE_TYPE.PICTURE
                or (shape.has_text_frame and shape.text_frame.text.strip())]
        if not heading_text and not body:
            continue
        if heading_text:
            heading = document.add_heading(heading_text, level=1)
            heading.paragraph_format.page_break_before = not first_content
        first_content = False
        for shape in body:
            if shape.has_table:
                _copy_table(document, shape.table, scale)
                document.add_paragraph()
            elif getattr(shape, 'has_chart', False):
                image = _chart_image(shape.chart, min(usable, shape.width / EMU_PER_INCH * scale), shape.height / EMU_PER_INCH * scale)
                if image is not None:
                    document.add_picture(image, width=Inches(min(usable, shape.width / EMU_PER_INCH * scale)))
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                document.add_picture(BytesIO(shape.image.blob), width=Inches(min(usable, shape.width / EMU_PER_INCH * scale)))
            else:
                for paragraph in shape.text_frame.paragraphs:
                    text = ''.join(run.text for run in paragraph.runs).strip()
                    if text:
                        # Keep the colour of coloured notes, such as the orange scaling notice.
                        run = document.add_paragraph().add_run(text)
                        font = paragraph.runs[0].font if paragraph.runs else paragraph.font
                        colour = font.color.rgb if font.color and font.color.type is not None else (
                            paragraph.font.color.rgb if paragraph.font.color and paragraph.font.color.type is not None else None)
                        if colour is not None and str(colour).upper() not in {'FFFFFF'}:
                            run.font.color.rgb = RGBColor.from_string(str(colour))
                        run.font.bold = bool(paragraph.font.bold or (paragraph.runs and paragraph.runs[0].font.bold))
    output = BytesIO()
    document.save(output)
    return output.getvalue()
