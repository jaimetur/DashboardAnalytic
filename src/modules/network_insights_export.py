"""PowerPoint and Word summaries of a Network Insights analysis."""
from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Inches as DocxInches, Pt as DocxPt
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image
from pptx.enum.text import MSO_AUTO_SIZE
from pptx import Presentation
from pptx.util import Inches, Pt

from src.modules.exports import MUTED, ORANGE, _add_textbox
from src.utils.fonts import load_image_font

# Renders a Canvas chart model to PNG bytes at the requested pixel size.
ChartRenderer = Callable[[dict[str, Any], int, int], bytes]

TABLE_ROWS_PER_SLIDE = 12


def _number(value: Any, digits: int = 1, suffix: str = '') -> str:
    if value is None or value == '':
        return '—'
    if isinstance(value, (int, float)):
        return f'{value:,.{digits}f}{suffix}' if isinstance(value, float) else f'{value:,}{suffix}'
    return str(value)


def _signed(value: Any, suffix: str = '') -> str:
    return '—' if value is None else f'{value:+.1f}{suffix}'


def summary_selection_lines(selection: dict[str, Any]) -> list[str]:
    """Readable lines describing the analysed CDRs, grouping and filters."""
    lines = [
        *([f"NR Mode: {selection['nr_mode']}"] if selection.get('nr_mode') else []),
        f"Technology: {selection.get('technology_label') or selection.get('technology') or 'LTE'}",
        f"Grouping: {selection.get('group_label') or 'Operator → Campaign'}",
    ]
    technology = selection.get('technology') or 'lte'
    for radio, label, coverage, interference in (('lte', 'LTE', 'coverage_threshold', 'interference_threshold'),
                                                  ('nr', 'NR', 'nr_coverage_threshold', 'nr_interference_threshold')):
        if technology in {radio, 'lte_nr'} and selection.get(coverage) is not None:
            lines.append(f"{label} thresholds: low coverage below {selection.get(coverage)} dBm RSRP, "
                         f"high interference below {selection.get(interference)} dB SINR")
    for label, key in (('Operators', 'operators'), ('Operator_Vendor', 'operator_vendors'), ('Vendors', 'vendors'),
                       ('Campaigns', 'campaigns'), ('Regions', 'regions'), ('Clusters', 'clusters'), ('Cities', 'cities')):
        values = selection.get(key) or []
        lines.append(f"{label}: {', '.join(values) if values else 'All'}")
    datasets = selection.get('dataset_names') or []
    lines.append(f"CDRs ({len(datasets)}): {', '.join(datasets) if datasets else 'All ready CDRs'}")
    return lines


def technology_sections(analysis: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(title suffix, section) per technology; LTE+NR exports LTE and NR separately."""
    sections = analysis.get('sections') or [analysis]
    if len(sections) == 1:
        return [('', sections[0])]
    return [(f" · {section.get('technology_label') or section.get('technology')}", section) for section in sections]


def overview_table(analysis: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    comparison = analysis.get('comparison')
    columns = ['Group', 'Samples', 'RSRP mean', 'RSRP median', 'RSRP P10', 'Low cov. %',
               'SINR mean', 'SINR median', 'SINR P10', 'High interf. %', 'eNodeBs', 'Cells']
    if comparison:
        columns += [f'Δ RSRP med. ({comparison["latest"]} vs {comparison["previous"]})', 'Δ Low cov.', 'Δ SINR med.', 'Δ High interf.']
    rows = []
    for row in analysis.get('rf_rows') or analysis.get('overview') or []:
        values = [str(row.get('operator') or ''), _number(row.get('samples'), 0), _number(row.get('rsrp_mean')), _number(row.get('rsrp_median')),
                  _number(row.get('rsrp_p10')), _number(row.get('low_coverage_share'), suffix='%'), _number(row.get('sinr_mean')),
                  _number(row.get('sinr_median')), _number(row.get('sinr_p10')), _number(row.get('high_interference_share'), suffix='%'),
                  _number(row.get('observed_enodebs'), 0), _number(row.get('observed_cells'), 0)]
        if comparison:
            deltas = row.get('deltas') or {}
            values += [_signed(deltas.get('rsrp_median')), _signed(deltas.get('low_coverage_share'), ' pp'),
                       _signed(deltas.get('sinr_median')), _signed(deltas.get('high_interference_share'), ' pp')]
        rows.append(values)
    return columns, rows


def hotspot_table(rows: list[dict[str, Any]], unit: str, limit: int = 10) -> tuple[list[str], list[list[str]]]:
    columns = ['City', 'Region', 'Samples', f'Mean ({unit})', 'Share below threshold', 'Latitude', 'Longitude']
    return columns, [
        [row.get('city') or '—', row.get('region') or '—', _number(row.get('samples'), 0), _number(row.get('mean')),
         _number(row.get('bad_share'), suffix='%'), f"{row.get('latitude')}", f"{row.get('longitude')}"]
        for row in rows[:limit]
    ]


def spectrum_tables(analysis: dict[str, Any]) -> list[tuple[str, list[str], list[list[str]]]]:
    spectrum = analysis.get('spectrum') or {}
    observed = [
        [row.get('operator') or '', row.get('technology') or '', row.get('band') or '', row.get('band_class') or '',
         _number(row.get('share'), suffix='%'), _number(row.get('samples'), 0), _number(row.get('typical_bandwidth_mhz'), 0, ' MHz')]
        for row in spectrum.get('observed') or []
    ]
    licensed = [
        [row.get('operator') or '', _number(row.get('Low')), _number(row.get('Mid')), _number(row.get('High (TDD)')), _number(row.get('total'))]
        for row in spectrum.get('licensed') or []
    ]
    tables = []
    if observed:
        tables.append(('Observed Spectrum', ['Group', 'Technology', 'Band', 'Class', 'Share', 'Samples', 'Typical bandwidth'], observed))
    if licensed:
        tables.append(('Licensed Spectrum (MHz)', ['Operator', 'Low', 'Mid', 'High (TDD)', 'Total'], licensed))
    return tables


def deployment_tables(deployment: dict[str, Any]) -> list[tuple[str, list[str], list[list[str]]]]:
    if 'groupings' in deployment:
        return [table for grouping in deployment['groupings'] for table in deployment_tables(grouping)]
    tables = []
    for inventory in deployment.get('inventories') or []:
        rows = [[row['group'], _number(row['sites'], 0), _number(row['cells'], 0)] for row in inventory.get('rows') or []]
        totals = inventory.get('totals') or {}
        if totals:
            rows.append(['Total', _number(totals.get('sites'), 0), _number(totals.get('cells'), 0)])
        if rows:
            tables.append((f"Network Deployment · {deployment.get('group_label') or 'All'} · {inventory.get('operator')} ({inventory.get('file_name')})",
                           [deployment.get('group_label') or 'Group', 'Sites', 'Cells'], rows))
    return tables


def cluster_sites_tables(analysis: dict[str, Any], deployment: dict[str, Any]) -> list[tuple[str, list[str], list[list[str]]]]:
    """Export both data sources independently of the panel's selected view."""
    observed = [[row.get('operator') or '', _number(row.get('observed_enodebs'), 0),
                 _number(row.get('observed_cells'), 0), _number(row.get('samples'), 0),
                 _number(row['samples'] / row['observed_enodebs']) if row.get('observed_enodebs') else '—']
                for _suffix, section in technology_sections(analysis) for row in _labelled_rows(analysis, section)]
    inventory = [[row['operator'], _number(row['sites'], 0), _number(row['cells'], 0)]
                 for row in (deployment.get('cluster_inventories') or {}).get('rows') or []]
    tables = []
    if observed:
        tables.append(('Cluster Sites Density · Observed Sites/Cells',
                       ['Group', 'Observed eNodeBs', 'Observed cells', 'Samples', 'Samples per eNodeB'], observed))
    if inventory:
        tables.append(('Cluster Sites Density · Inventory Sites/Cells',
                       ['Operator', 'Inventory sites', 'Inventory cells'], inventory))
    return tables


def _labelled_rows(analysis: dict[str, Any], section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = section.get('rf_rows') or []
    if len(analysis.get('sections') or []) < 2:
        return rows
    return [{**row, 'operator': f"{row.get('operator') or ''} · {section.get('technology_label') or ''}"} for row in rows]


def _chart_images(analysis: dict[str, Any], render: ChartRenderer) -> list[tuple[str, BytesIO | None, str]]:
    """(title, PNG or None, note) for both CDFs and both maps."""
    charts = analysis.get('charts') or {}
    maps = analysis.get('maps') or {}
    items = [
        ('RSRP Distribution', charts.get('rsrp_cdf')), ('SINR Distribution', charts.get('sinr_cdf')),
        ('Coverage Map', maps.get('coverage')), ('Interference Map', maps.get('interference')),
    ]
    images = []
    for title, payload in items:
        if not isinstance(payload, dict):
            continue
        try:
            images.append((title, BytesIO(render(payload, 1600, 900)), ''))
        except Exception as exc:  # A chart that cannot be drawn must not drop the whole summary.
            images.append((title, None, f'The chart could not be rendered: {exc}'))
    return images


def _single_line(value: Any) -> str:
    """Keep table values intact while removing explicit line-break characters."""
    return ' '.join(str(value).splitlines())


def _column_text_widths(columns: list[str], rows: list[list[str]]) -> list[float]:
    """Estimate text widths in points at 1 pt, reserving space for font substitution."""
    normal, bold = load_image_font(100), load_image_font(100, bold=True)
    return [max(float(bold.getlength(_single_line(label))),
                max((float(normal.getlength(_single_line(row[index]))) for row in rows), default=0)) / 100 * 1.15
            for index, label in enumerate(columns)]


def _table_geometry(columns: list[str], rows: list[list[str]], width: float, maximum_font: float = 10) -> tuple[list[float], float]:
    measured = _column_text_widths(columns, rows)
    padding = 0.14 * 72
    font = min(maximum_font, (width * 72 - padding * len(columns)) / max(sum(measured), 1))
    font = max(1, font)
    required = [length * font + padding for length in measured]
    scale = width / sum(required)
    return [value * scale for value in required], font


def _ppt_table_parts(columns: list[str], rows: list[list[str]], width: float):
    """Repeat the identity column if a wide comparison needs multiple metric panels."""
    measured = _column_text_widths(columns, rows)
    indices, parts = [0], []
    for index in range(1, len(columns)):
        proposed = [*indices, index]
        if len(indices) > 1 and sum(measured[item] * 8 + 0.14 * 72 for item in proposed) > width * 72:
            parts.append(indices)
            indices = [0]
        indices.append(index)
    parts.append(indices)
    return [([columns[index] for index in part], [[row[index] for index in part] for row in rows]) for part in parts]


def _add_table(slide, columns: list[str], rows: list[list[str]], left: float, top: float, width: float) -> None:
    shape = slide.shapes.add_table(len(rows) + 1, len(columns), Inches(left), Inches(top), Inches(width), Inches(0.32 * (len(rows) + 1)))
    table = shape.table
    widths, font_size = _table_geometry(columns, rows, width)
    for index, column_width in enumerate(widths):
        table.columns[index].width = Inches(column_width)
    for row_index, values in enumerate([columns, *rows]):
        for column, value in enumerate(values):
            cell = table.cell(row_index, column)
            cell.text = _single_line(value)
            cell.margin_left = cell.margin_right = Inches(0.05)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.text_frame.word_wrap = False
            for paragraph in cell.text_frame.paragraphs:
                paragraph.space_before = paragraph.space_after = Pt(0)
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.bold = row_index == 0


def _content_frame(slide) -> tuple[float, float, float, float]:
    layout = slide.slide_layout
    shapes = [shape for shape in layout.placeholders if shape.placeholder_format.type not in {1, 3, 4}]
    shape = max(shapes, key=lambda item: item.width * item.height)
    return tuple(value / 914400 for value in (shape.left, shape.top, shape.width, shape.height))


def _slide(presentation: Presentation, title: str, subtitle: str = ''):
    from src.modules.cdr_reporting import _named_slide_layout, _remove_template_chart_placeholders, _set_slide_header

    layout = _named_slide_layout(presentation, 'Title + 1 rows + 1 columns')
    if layout is None:
        raise ValueError('The Dashboard template requires the Title + 1 rows + 1 columns layout.')
    slide = presentation.slides.add_slide(layout)
    _set_slide_header(slide, title, subtitle)
    _remove_template_chart_placeholders(slide)
    for placeholder in slide.placeholders:
        if placeholder.has_text_frame:
            placeholder.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    return slide


def _table_slides(presentation: Presentation, title: str, columns: list[str], rows: list[list[str]], subtitle: str = '') -> None:
    from src.modules.cdr_reporting import _named_slide_layout

    layout = _named_slide_layout(presentation, 'Title + 1 rows + 1 columns')
    content = max((shape for shape in layout.placeholders if shape.placeholder_format.type not in {1, 3, 4}),
                  key=lambda shape: shape.width * shape.height)
    parts = _ppt_table_parts(columns, rows, content.width / 914400)
    for part_index, (part_columns, part_rows) in enumerate(parts, start=1):
        pages = [part_rows[index:index + TABLE_ROWS_PER_SLIDE] for index in range(0, len(part_rows), TABLE_ROWS_PER_SLIDE)] or [[]]
        for page_number, page in enumerate(pages, start=1):
            page_title = title + (f' · Part {part_index}/{len(parts)}' if len(parts) > 1 else '')
            if len(pages) > 1:
                page_title += f' · {page_number}/{len(pages)}'
            slide = _slide(presentation, page_title, subtitle)
            left, top, width, _height = _content_frame(slide)
            if page:
                _add_table(slide, part_columns, page, left, top, width)
            else:
                _add_textbox(slide, left, top, width, 0.3, 'No data for this selection.', size=12, color=MUTED)


def export_network_insights_powerpoint(destination: Path, analysis: dict[str, Any], deployment: dict[str, Any],
                                       selection: dict[str, Any], render: ChartRenderer, template: Path | None = None) -> Path:
    from src.config import settings
    from src.modules.cdr_reporting import _named_slide_layout, _remove_all_slides, _set_structural_slide_text

    presentation = Presentation(template or settings.ppt_templates_dir / 'Template_CDR_analysis.pptx')
    _remove_all_slides(presentation)
    cover = presentation.slides.add_slide(_named_slide_layout(presentation, 'Title Page'))
    _set_structural_slide_text(cover, 'Summary Network Insights', 'Dashboard Analytic')
    selection_slide = _slide(presentation, 'Analysis Selection')
    left, top, width, height = _content_frame(selection_slide)
    shape = selection_slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    shape.text_frame.word_wrap = True
    shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for index, line in enumerate(summary_selection_lines(selection)):
        paragraph = shape.text_frame.paragraphs[0] if index == 0 else shape.text_frame.add_paragraph()
        paragraph.text = line
        paragraph.font.size = Pt(15)
    for suffix, section in technology_sections(analysis):
        columns, rows = overview_table(section)
        _table_slides(presentation, f'RF Quality Overview{suffix}', columns, rows, selection.get('group_label') or '')
    images = [(f'{title}{suffix}', image, note) for suffix, section in technology_sections(analysis)
              for title, image, note in _chart_images(section, render)]
    for title, image, note in images:
        slide = _slide(presentation, title)
        if image is not None:
            left, top, width, height = _content_frame(slide)
            with Image.open(image) as raster:
                ratio = raster.width / raster.height
            image.seek(0)
            picture_width = min(width, height * ratio)
            picture_height = picture_width / ratio
            slide.shapes.add_picture(image, Inches(left + (width - picture_width) / 2), Inches(top),
                                     width=Inches(picture_width), height=Inches(picture_height))
        else:
            _add_textbox(slide, 0.55, 1.3, 12.2, 0.3, note, size=12, color=ORANGE)
    for suffix, section in technology_sections(analysis):
        maps = section.get('maps') or {}
        for title, key, unit in (('Weakest Coverage Areas', 'coverage_hotspots', 'dBm'), ('Highest Interference Areas', 'interference_hotspots', 'dB')):
            columns, rows = hotspot_table(maps.get(key) or [], unit)
            _table_slides(presentation, f'{title}{suffix}', columns, rows, f"Map operator: {maps.get('operator') or '—'}")
    for title, columns, rows in [*spectrum_tables(analysis), *deployment_tables(deployment), *cluster_sites_tables(analysis, deployment)]:
        _table_slides(presentation, title, columns, rows)
    warnings = analysis.get('warnings') or []
    if warnings:
        slide = _slide(presentation, 'Analysis Notes')
        left, top, width, height = _content_frame(slide)
        shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        shape.text_frame.text = '\n'.join(str(warning) for warning in warnings)
        shape.text_frame.word_wrap = True
        shape.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    closing = _named_slide_layout(presentation, 'Black logo end slide')
    if closing is not None:
        _set_structural_slide_text(presentation.slides.add_slide(closing), '', '')
    presentation.save(destination)
    return destination


def _docx_table(document: Document, columns: list[str], rows: list[list[str]]) -> None:
    table = document.add_table(rows=1, cols=len(columns))
    table.style = 'Light Grid Accent 1'
    table.autofit = False
    section = document.sections[-1]
    width = (section.page_width - section.left_margin - section.right_margin) / 914400
    widths, font = _table_geometry(columns, rows, width, maximum_font=9)
    for index, value in enumerate(widths):
        table.columns[index].width = DocxInches(value)
    for row_index, values in enumerate([columns, *rows]):
        row = table.rows[0] if row_index == 0 else table.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        if row_index == 0:
            row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        for index, value in enumerate(values):
            cell = row.cells[index]
            cell.width = DocxInches(widths[index])
            cell.text = _single_line(value)
            properties = cell._tc.get_or_add_tcPr()
            properties.append(OxmlElement('w:noWrap'))
            margins = OxmlElement('w:tcMar')
            for side in ('top', 'bottom', 'left', 'right'):
                item = OxmlElement(f'w:{side}')
                item.set(qn('w:w'), '72' if side in {'left', 'right'} else '36')
                item.set(qn('w:type'), 'dxa')
                margins.append(item)
            properties.append(margins)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = paragraph.paragraph_format.space_after = DocxPt(0)
                paragraph.paragraph_format.line_spacing = 1
                for run in paragraph.runs:
                    run.font.name = 'Arial'
                    run.font.size = DocxPt(font)
                    run.bold = row_index == 0


def export_network_insights_word(destination: Path, analysis: dict[str, Any], deployment: dict[str, Any],
                                 selection: dict[str, Any], render: ChartRenderer) -> Path:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = DocxInches(11.69), DocxInches(8.27)
    section.left_margin = section.right_margin = DocxInches(0.6)
    section.top_margin = section.bottom_margin = DocxInches(0.6)
    tables = [*(overview_table(section) for _suffix, section in technology_sections(analysis)),
              *(hotspot_table((section.get('maps') or {}).get(key) or [], unit) for _suffix, section in technology_sections(analysis)
                for key, unit in [('coverage_hotspots', 'dBm'), ('interference_hotspots', 'dB')]),
              *((columns, rows) for _title, columns, rows in [*spectrum_tables(analysis), *deployment_tables(deployment), *cluster_sites_tables(analysis, deployment)])]
    needed = max((sum(length * 9 + 0.14 * 72 for length in _column_text_widths(columns, rows)) / 72
                  for columns, rows in tables), default=0)
    if needed > 10.49:
        section.page_width = DocxInches(max(16.54, min(22, needed + 1.2)))
        section.page_height = DocxInches(11.69)
    document.add_heading('Dashboard Analytic · Summary Network Insights', level=0)
    for line in summary_selection_lines(selection):
        document.add_paragraph(line, style='List Bullet')
    for warning in analysis.get('warnings') or []:
        document.add_paragraph(f'Warning: {warning}')
    for suffix, section in technology_sections(analysis):
        document.add_heading(f'RF Quality Overview{suffix}', level=1)
        columns, rows = overview_table(section)
        _docx_table(document, columns, rows)
    for suffix, section in technology_sections(analysis):
        for title, image, note in _chart_images(section, render):
            document.add_heading(f'{title}{suffix}', level=1)
            if image is not None:
                document.add_picture(image, width=DocxInches(6.3))
            else:
                document.add_paragraph(note)
    for suffix, section in technology_sections(analysis):
        maps = section.get('maps') or {}
        for title, key, unit in (('Weakest Coverage Areas', 'coverage_hotspots', 'dBm'), ('Highest Interference Areas', 'interference_hotspots', 'dB')):
            document.add_heading(f'{title}{suffix}', level=1)
            columns, rows = hotspot_table(maps.get(key) or [], unit)
            if rows:
                _docx_table(document, columns, rows)
            else:
                document.add_paragraph('No area falls below the threshold for this selection.')
    for title, columns, rows in [*spectrum_tables(analysis), *deployment_tables(deployment), *cluster_sites_tables(analysis, deployment)]:
        document.add_heading(title, level=1)
        _docx_table(document, columns, rows)
    document.save(destination)
    return destination

