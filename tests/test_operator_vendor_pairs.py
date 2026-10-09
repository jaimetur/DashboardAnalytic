"""Operator_Vendor and Vendor_Operator filters stay in sync everywhere."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WEB = ROOT / 'src/web_interface'
HELPER = (WEB / 'static/js/operator_vendor_pairs.js').read_text(encoding='utf-8')

# Minimal DOM: two native multi-selects in one container, as in Network Insights, NQ, Scoring and E2E Dashboards.
PROGRAM = '''
const listeners = [];
globalThis.document = {addEventListener: (type, listener) => { if (type === 'change') listeners.push(listener); }};
class HTMLSelectElement {
  constructor(kind, values, container) {
    this.dataset = {operatorVendorPair: kind};
    this.options = values.map(value => ({value, selected: false}));
    this.parentElement = container;
    this.events = [];
  }
  get selectedOptions() { return this.options.filter(option => option.selected); }
  dispatchEvent(event) { this.events.push(event.type); if (event.type === 'change') listeners.forEach(listener => listener({target: this})); }
}
globalThis.HTMLSelectElement = HTMLSelectElement;
globalThis.Event = class { constructor(type) { this.type = type; } };
const container = {parentElement: null, querySelector: selector => selects.find(select => selector.includes(`"${select.dataset.operatorVendorPair}"`))};
const selects = [
  new HTMLSelectElement('operator_vendor', ['VF_UK_Ericsson', 'VF_UK_Nokia', '3_Ericsson (Mixed)', 'EE - All'], container),
  new HTMLSelectElement('vendor_operator', ['Ericsson_VF_UK', 'Nokia_VF_UK', 'Ericsson (Mixed)_3', 'EE - All'], container),
];
''' + HELPER + '''
const [operatorVendor, vendorOperator] = selects;
const {pairedValue, mirrorValues} = globalThis.operatorVendorPairs;
const result = {
  paired: pairedValue('VF_UK_Ericsson', new Set(['Ericsson_VF_UK', 'Nokia_VF_UK'])),
  mirrored: mirrorValues(['Ericsson (Mixed)_3', 'EE - All'], operatorVendor.options.map(option => option.value)),
};
operatorVendor.options[0].selected = true;
operatorVendor.options[2].selected = true;
operatorVendor.dispatchEvent(new Event('change'));
result.vendorOperator = vendorOperator.selectedOptions.map(option => option.value);
result.vendorOperatorEvents = [...vendorOperator.events];
vendorOperator.options.forEach(option => { option.selected = option.value === 'EE - All'; });
vendorOperator.dispatchEvent(new Event('change'));
result.operatorVendor = operatorVendor.selectedOptions.map(option => option.value);
console.log(JSON.stringify(result));
'''


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_native_operator_vendor_filters_mirror_each_other():
    completed = subprocess.run(['node', '-e', PROGRAM], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result['paired'] == 'Ericsson_VF_UK'
    assert result['mirrored'] == ['3_Ericsson (Mixed)', 'EE - All']
    assert result['vendorOperator'] == ['Ericsson_VF_UK', 'Ericsson (Mixed)_3']
    assert result['vendorOperatorEvents'] == ['change', 'input']
    assert result['operatorVendor'] == ['EE - All']


# The same DOM with a Vendor select, as in CDR Analysis.
VENDOR_PROGRAM = PROGRAM.split(HELPER)[0].replace(
    "  new HTMLSelectElement('vendor_operator', ['Ericsson_VF_UK', 'Nokia_VF_UK', 'Ericsson (Mixed)_3', 'EE - All'], container),\n",
    "  new HTMLSelectElement('vendor_operator', ['Ericsson_VF_UK', 'Nokia_VF_UK', 'Ericsson (Mixed)_3', 'EE - All'], container),\n"
    "  new HTMLSelectElement('vendor', ['Ericsson', 'Nokia', 'Ericsson (Mixed)', 'EE - All'], container),\n",
) + HELPER + '''
const [operatorVendor, vendorOperator, vendor] = selects;
const chosen = select => select.selectedOptions.map(option => option.value);
const result = {};
// Choosing Vendors chooses their Operator_Vendor and Vendor_Operator values.
vendor.options.forEach(option => { option.selected = ['Ericsson', 'EE - All'].includes(option.value); });
vendor.dispatchEvent(new Event('change'));
result.fromVendor = {operatorVendor: chosen(operatorVendor), vendorOperator: chosen(vendorOperator)};
// Choosing Operator_Vendor values chooses their Vendors (Ericsson (Mixed) is not Ericsson) and Vendor_Operator values.
operatorVendor.options.forEach(option => { option.selected = ['VF_UK_Nokia', '3_Ericsson (Mixed)'].includes(option.value); });
operatorVendor.dispatchEvent(new Event('change'));
result.fromOperatorVendor = {vendor: chosen(vendor), vendorOperator: chosen(vendorOperator)};
// And from Vendor_Operator.
vendorOperator.options.forEach(option => { option.selected = option.value === 'Ericsson_VF_UK'; });
vendorOperator.dispatchEvent(new Event('change'));
result.fromVendorOperator = {vendor: chosen(vendor), operatorVendor: chosen(operatorVendor)};
console.log(JSON.stringify(result));
'''


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_vendor_filter_stays_in_sync_with_operator_vendor_and_vendor_operator():
    completed = subprocess.run(['node', '-e', VENDOR_PROGRAM], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result['fromVendor'] == {'operatorVendor': ['VF_UK_Ericsson', 'EE - All'], 'vendorOperator': ['Ericsson_VF_UK', 'EE - All']}
    assert result['fromOperatorVendor'] == {'vendor': ['Nokia', 'Ericsson (Mixed)'], 'vendorOperator': ['Nokia_VF_UK', 'Ericsson (Mixed)_3']}
    assert result['fromVendorOperator'] == {'vendor': ['Ericsson'], 'operatorVendor': ['VF_UK_Ericsson']}


def test_every_operator_vendor_filter_is_paired():
    assert "js/operator_vendor_pairs.js" in (WEB / 'templates/base.html').read_text(encoding='utf-8')
    analysis = (WEB / 'templates/datasets_analysis.html').read_text(encoding='utf-8')
    assert 'data-operator-vendor-pair="{{ dimension }}"' in analysis
    for template in ('non_qualified_calls.html', 'network_insights.html'):
        markup = (WEB / 'templates' / template).read_text(encoding='utf-8')
        assert 'data-operator-vendor-pair="operator_vendor"' in markup
        assert 'data-operator-vendor-pair="vendor_operator"' in markup
    scoring = (WEB / 'templates/scoring.html').read_text(encoding='utf-8')
    assert 'data-operator-vendor-pair="{{ field | lower }}"' in scoring
    dashboards = (WEB / 'static/js/e2e_dashboards.js').read_text(encoding='utf-8')
    assert "values.dataset.operatorVendorPair = 'vendor_operator'" in dashboards
    for script in ('report_jobs.js', 'scoring_report_editor.js'):
        assert 'operatorVendorPairs.mirrorValues(' in (WEB / 'static/js' / script).read_text(encoding='utf-8')


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is required')
def test_vendor_operator_choices_order_ericsson_mixed_with_ericsson_and_other_mixed_groups_last():
    script = (WEB / 'static/js/app.js').read_text(encoding='utf-8')
    start = script.index('function vendorOnlyFilterChoices(')
    end = script.index('window.vendorOnlyFilterChoices = vendorOnlyFilterChoices;', start)
    configured = {
        'operators': {'3': '3', 'VF_UK': 'VF_UK', 'EE': 'EE'}, 'operator_order': ['3', 'VF_UK', 'EE'],
        'vendors': {'Ericsson': 'Ericsson', 'Huawei': 'Huawei', 'Ericsson (Mixed)': 'Ericsson (Mixed)',
                    'Mixed (non-Ericsson)': 'Mixed (non-Ericsson)'},
        'vendor_order': ['Ericsson', 'Huawei', 'Ericsson (Mixed)', 'Mixed (non-Ericsson)'],
    }
    program = (
        f"globalThis.document = {{getElementById: () => ({{textContent: {json.dumps(json.dumps(configured))}}})}};\n"
        + script[start:end]
        + "\nconst values = ['Mixed (non-Ericsson)_3', 'Ericsson (Mixed)_VF_UK', 'Huawei_3', 'Ericsson_VF_UK', 'Ericsson (Mixed)_3',"
          " 'Ericsson_3', 'EE - All'];\n"
          "console.log(JSON.stringify(vendorOnlyFilterChoices('Vendor_Operator', values).map(choice => choice.value)));"
    )
    completed = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == [
        'Ericsson_3', 'Ericsson (Mixed)_3', 'Ericsson_VF_UK', 'Ericsson (Mixed)_VF_UK', 'Huawei_3', 'EE - All', 'Mixed (non-Ericsson)_3']
