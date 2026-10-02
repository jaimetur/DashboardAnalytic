from pathlib import Path

import pytest

from tests.test_scoring_exports import (
    MAPPED_OPERATOR_COLORS, _export, _mapping_groups, _result,
)


@pytest.mark.parametrize('levels', [('Operator',), ('Operator', 'Region'), ('Region', 'Operator')])
def test_gap_operator_headers_use_mapping_fill_in_combined_and_individual_slides(levels):
    presentation = _export(_result(), levels=levels, operator_mapping_groups=_mapping_groups())
    tables = [shape.table for slide in presentation.slides
              if slide.shapes.title and slide.shapes.title.text.startswith('GAP Analysis')
              for shape in slide.shapes if shape.has_table]
    assert tables
    mapped_count = 0
    for table in tables:
        for row in table.rows:
            for cell in row.cells:
                for label, color in MAPPED_OPERATOR_COLORS.items():
                    short_label = {'Three UK': '3', 'O2 UK': 'O2', 'Vodafone UK': 'VF'}.get(label, label)
                    if cell.text in {f'{label} − EE', f'{short_label} − EE'}:
                        assert str(cell.fill.fore_color.rgb) == color.lstrip('#').upper()
                        mapped_count += 1
    assert mapped_count >= 3


def test_web_gap_headers_preserve_hierarchy_and_use_operator_fill():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'src/web_interface/static/js/scoring.js').read_text()
    template = (root / 'src/web_interface/templates/scoring.html').read_text()
    assert 'const row = gapBaseline && depthIndex === 0 ? firstRow' in script
    assert 'for (const block of gapBaseline ? [] : blocks)' in script
    assert '], blocks, baseline);' in script
    assert "th.style.setProperty('--operator-text', categoryLegendTextColor(presentation.color));" in script
    assert 'th.scoring-gap-header.scoring-gap-operator-header { background: color-mix(in srgb, var(--operator-accent' in template


@pytest.mark.parametrize('levels', [['Operator'], ['Region', 'Operator']])
def test_web_gap_hierarchy_headers_render_comparisons_without_extra_row(levels):
    from tests.test_scoring_results_controls import _function_source, _run_node_json, SCORING_SCRIPT

    script = SCORING_SCRIPT.read_text()
    functions = '\n'.join(_function_source(script, name) for name in (
        'appendHierarchyHeaders', 'hierarchyLevelNames', 'hierarchyDisplayValue', 'hierarchyPathEntry', 'hierarchyPrefixKey',
    ))
    program = r'''
const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const document = {createElement() { return {
  children: [], dataset: {}, textContent: '', styles: {},
  append(child) {this.children.push(child);},
  setAttribute() {}, classList: {add() {}},
  style: {setProperty(name, value) {this.owner.styles[name] = value;}},
};}};
const originalCreate = document.createElement;
document.createElement = () => {const el = originalCreate(); el.style.owner = el; return el;};
const operatorPresentation = (_, id) => ({label: id, color: '#3456AB'});
const canonicalOperatorName = value => value;
const hierarchyPathFullLabel = column => column.id;
const hierarchyColumnIsReference = () => false;
const categoryLegendTextColor = () => '#ffffff';
const columns = ['3', 'O2'].map(id => ({id, path: payload.levels.map(level => ({
  level, value: level === 'Operator' ? id : 'North',
}))}));
const thead = document.createElement('thead');
''' + functions + r'''
appendHierarchyHeaders(thead, {hierarchy_levels: payload.levels}, columns,
  [['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type']],
  [{label: 'All vs EE', headerClass: 'scoring-gap-header', columns}], 'EE');
console.log(JSON.stringify(thead.children.map(row => row.children.map(cell => ({
  text: cell.textContent, span: cell.rowSpan, columns: cell.colSpan, styles: cell.styles,
})))));
'''
    rows = _run_node_json(program, {'levels': levels})
    assert len(rows) == len(levels)
    assert [cell['text'] for cell in rows[-1][-2:]] == ['3 − EE', 'O2 − EE']
    assert all(cell['span'] == len(levels) for cell in rows[0][:3])
    assert all(cell['styles']['--operator-accent'] == '#3456AB' for cell in rows[-1][-2:])
    assert not any(cell['text'] == 'All vs EE' for row in rows for cell in row)
    if len(levels) > 1:
        assert rows[0][-1]['text'] == 'North'
        assert rows[0][-1]['columns'] == 2
