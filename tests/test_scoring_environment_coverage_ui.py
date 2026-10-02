"""Coverage defaults and explanations follow the selected scoring environment."""
import pytest
from tests.test_scoring_results_controls import SCORING_SCRIPT, _run_node_json


def _coverage_case(totals, selected='all', apply_default=True, extra_environment=None):
    source = SCORING_SCRIPT.read_text()
    helpers = source[source.index('  const environmentOrder ='):source.index('  function chartRowsForEnvironment')]
    program = r'''
const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const document = {createElement: () => ({})};
let selectedEnvironment = payload.selected, currentEffectiveEnvironment;
const environmentSelect = {options: [], replaceChildren() {this.options=[];}, append(option) {this.options.push(option);}};
const environmentControl = {};
const formatChartNumber = value => String(value);
''' + helpers + r'''
const data = {totals: payload.totals, aggregation_levels: ['Operator', 'City', 'Campaign'],
 configuration: {scope: {environments: {DriveCity: {total_points: 650}, Roads: {total_points: 350}}}},
 warnings: ['Incomplete KPI or environment coverage: partial points are shown without renormalizing weights; a complete benchmark score is unavailable.', 'Independent source warning.']};
if (payload.extraEnvironment) data.configuration.scope.environments[payload.extraEnvironment] = {total_points: 100};
const tables = payload.totals.map(row => ({context: {environment: row.environment}}));
const selection = syncResultEnvironment(tables, {payload: data, applyCoverageDefault: payload.applyDefault});
const job = {context_filters: {City: ['Leeds', 'London']}};
process.stdout.write(JSON.stringify({selected: selectedEnvironment, selection, options: environmentSelect.options,
 warnings: scoringCoverageWarnings(data, job, selection.effective),
 cardWarnings: scoringCoverageWarnings({...data, warnings: []}, job, selection.effective, {concise: true})}));
'''
    return _run_node_json(program, {'totals': totals, 'selected': selected, 'applyDefault': apply_default, 'extraEnvironment': extra_environment})


def _total(environment, complete, available=650, maximum=650):
    return {'environment': environment, 'operator': 'EE', 'city': 'Leeds', 'campaign': '2026-Q1',
            'category': 'Overall', 'complete_coverage': complete,
            'available_points': available, 'max_points': maximum}


def test_incomplete_combined_defaults_to_complete_city_and_hides_its_coverage_warning():
    actual = _coverage_case([_total('DriveCity', True), _total('Combined', False, maximum=1000)])
    assert actual['selected'] == 'DriveCity'
    assert [option['textContent'] for option in actual['options']] == ['All Environments', 'DriveCity']
    assert actual['warnings'] == ['Independent source warning.']


def test_manual_combined_selection_explains_missing_roads_filters_and_aggregation():
    actual = _coverage_case([_total('DriveCity', True), _total('Combined', False, maximum=1000)], apply_default=False)
    assert actual['selected'] == 'all'
    assert actual['cardWarnings'] == ['Selected Environment has incomplete coverage because one of its Environments (Roads) has no data with the selected filters.']
    message = actual['warnings'][-1]
    for text in ('Missing weighted environments', 'Roads', '650 of 1000',
                 'saved City filter is Leeds, London', 'City is an aggregation level',
                 'not earned scores', 'not scaled up'):
        assert text in message
    assert 'Independent source warning.' in actual['warnings']


@pytest.mark.parametrize('city_complete, combined_complete, expected', [
    (True, True, 'all'), (False, False, 'all'),
])
def test_complete_combined_or_no_complete_environment_keeps_all(city_complete, combined_complete, expected):
    actual = _coverage_case([_total('DriveCity', city_complete), _total('Combined', combined_complete, maximum=1000)])
    assert actual['selected'] == expected


def test_default_preserves_an_individual_environment_choice_and_explains_missing_kpis():
    actual = _coverage_case([_total('DriveCity', False, 600), _total('Combined', False, 600, 1000)], selected='DriveCity')
    assert actual['selected'] == 'DriveCity'
    assert 'required KPI measurements' in actual['warnings'][-1]
    assert '600 of 650' in actual['warnings'][-1]


def test_default_skips_incomplete_city_and_chooses_the_next_complete_environment():
    actual = _coverage_case([
        _total('DriveCity', False, 600), _total('Roads', True, 350, 350),
        _total('Combined', False, 950, 1000),
    ], selected='DriveCity')
    assert actual['selected'] == 'Roads'
    assert actual['warnings'] == ['Independent source warning.']


def test_warning_lists_every_environment_without_data():
    actual = _coverage_case([_total('DriveCity', True), _total('Combined', False, maximum=1100)],
                            apply_default=False, extra_environment='Walk')
    assert actual['cardWarnings'] == [
        'Selected Environment has incomplete coverage because some of its Environments '
        '(Roads, Walk) have no data with the selected filters.'
    ]
