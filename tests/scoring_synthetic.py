"""Synthetic saved scoring results with several cities and campaigns, for views and exports."""
from __future__ import annotations

import random

from src.modules.scoring import _gap_rows, _gap_totals, _totals, environment_scaling, most_reliable_result
from tests.test_scoring_most_reliable import _reliable_configuration

OPERATORS = ('Vodafone UK', 'Three UK', 'EE', 'O2 UK')
CITIES = ('London', 'Leeds', 'Bristol', 'Cardiff')
CAMPAIGNS = ('2025-Q2', '2025-Q3', '2025-Q4', '2026-Q1', '2026-Q2')


def synthetic_result(levels=('Operator', 'City', 'Campaign'), cities=CITIES, campaigns=CAMPAIGNS,
                     operators=OPERATORS, seed=7):
    """A saved result whose KPI scores vary by operator, city and campaign."""
    configuration = _reliable_configuration()
    generator = random.Random(seed)
    strength = {operator: 0.86 + index * 0.03 for index, operator in enumerate(operators)}
    rows = []
    for campaign_index, campaign in enumerate(campaigns if 'Campaign' in levels else [None]):
        for city in cities if 'City' in levels else [None]:
            for environment in ('DriveCity', 'DriveConnectionroad'):
                for operator in operators:
                    for metric in configuration['metrics']:
                        context = metric['contexts'][environment]
                        base = strength[operator] + campaign_index * 0.01
                        score = max(0.0, min(1.0, generator.gauss(base, 0.08)))
                        rows.append({
                            'campaign': campaign, 'city': city, 'operator': operator, 'environment': environment,
                            'kpi_code': metric['code'], 'kpi': metric['kpi'], 'category': metric['category'],
                            'dataset_type': metric['source_kind'].title(), 'kpi_type': metric['kpi_type'],
                            'value': round(80 + score * 20, 3), 'sample_count': 100, 'score': score,
                            'max_points': context['max_points'], 'weighted_points': score * context['max_points'],
                        })
    keys = ['campaign', *[level.lower() for level in levels if level not in {'Campaign', 'Operator'}], 'operator',
            'environment']
    totals = _totals(rows, keys, configuration)
    result = {
        'scoring': rows, 'global_kpis': [], 'warnings': [], 'notices': [],
        'aggregation_levels': list(levels), 'aggregation_contract_version': 2,
        'configuration': configuration, 'baseline_aliases': ['EE'], 'gap_direction': 'operator_minus_reference',
        'totals': totals, 'charts': [dict(row) for row in totals],
        'gap': _gap_rows(rows, keys, 'EE', ['EE'], []), 'gap_totals': _gap_totals(totals, keys, 'EE', ['EE']),
        'environment_scaling': environment_scaling(totals), 'campaigns': list(campaigns),
    }
    job = {'levels': list(levels), 'aggregation_levels': list(levels), 'aggregation_contract_version': 2,
           'baseline_operator': 'EE', 'configuration': configuration, 'nr_mode': 'NSA', 'status': 'completed'}
    return job, result


__all__ = ['synthetic_result', 'most_reliable_result']
