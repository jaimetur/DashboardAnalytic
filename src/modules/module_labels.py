"""Main module tabs: their order, title, icon, colour and corner label.

Super-admins choose in Admin → Interface Settings, for every main module, its
position among the main tabs (also followed by the Modules menu, the Help
navigation and Features Activation), its title and short title for narrow
windows, its icon and colour, and the label shown in its corner: the label text
(empty for none), its colour and an optional predefined icon with its own
colour. The label text is drawn in white or dark ink, whichever reads better on
the chosen colour.
"""
from __future__ import annotations

import json
import re
from typing import Any

MODULE_LABELS_STATE_KEY = 'module_tab_labels_v1'
MAX_LABEL_LENGTH = 10
MAX_TITLE_LENGTH = 40
MAX_SHORT_TITLE_LENGTH = 20

# Main modules in tab order, with the name shown in Interface Settings.
MAIN_MODULES: tuple[tuple[str, str], ...] = (
    ('workspace', 'Workspace'),
    ('datasets-analysis', 'CDR Analysis'),
    ('e2e-dashboards', 'E2E Dashboards'),
    ('reporting-old', 'Reporting (old)'),
    ('scoring', 'Scoring & GAP Analysis'),
    ('network-insights', 'Network Insights'),
    ('non-qualified-calls', 'Non-Qualified Calls'),
    ('reporting', 'Reporting'),
    ('builders', 'Builders'),
)

# What each main tab links to and its default title, short title, Modules menu
# name, icon, colour (the accent of the module palette) and Help chapters.
MODULE_TABS: dict[str, dict[str, Any]] = {
    'workspace': {'css': 'module-tab-workspace', 'href': '/workspace', 'title': 'Workspace', 'short_title': 'Workspace',
                  'nav_title': 'Workspace Management', 'tab_icon': 'workspace', 'tab_color': '#08736D',
                  'docs': ('workspace-management.md',)},
    'datasets-analysis': {'css': 'module-tab-datasets-analysis', 'href': '/datasets-analysis', 'title': 'CDR Analysis',
                          'short_title': 'Analysis', 'nav_title': 'CDR Analysis', 'tab_icon': 'datasets-analysis',
                          'tab_color': '#1F6FBF', 'docs': ('datasets-analysis.md',)},
    'e2e-dashboards': {'css': 'module-tab-e2e-dashboards', 'href': '/e2e-dashboards', 'title': 'E2E Dashboards',
                       'short_title': 'Dashboards', 'nav_title': 'E2E Dashboard', 'tab_icon': 'e2e-dashboards',
                       'tab_color': '#7751B9', 'docs': ('e2e-dashboards.md',)},
    'reporting-old': {'css': 'module-tab-reporting', 'href': '/reporting-old', 'title': 'Reporting (old)',
                      'short_title': 'Reporting (old)', 'nav_title': 'Reporting (old)', 'tab_icon': 'reporting-old',
                      'tab_color': '#7650B5', 'docs': ('reporting-old.md',)},
    'scoring': {'css': 'module-tab-scoring', 'href': '/scoring', 'title': 'Scoring & GAP Analysis', 'short_title': 'Scoring',
                'nav_title': 'Scoring & GAP Analysis', 'tab_icon': 'scoring', 'tab_color': '#176E77',
                'docs': ('scoring-gap-analysis.md',)},
    'network-insights': {'css': 'module-tab-network-insights', 'href': '/network-insights', 'title': 'Network Insights',
                         'short_title': 'Network', 'nav_title': 'Network Insights', 'tab_icon': 'network-insights',
                         'tab_color': '#4F46E5', 'docs': ('network-insights.md',)},
    'non-qualified-calls': {'css': 'module-tab-non-qualified-calls', 'href': '/non-qualified-calls',
                            'title': 'Non-Qualified Calls', 'short_title': 'NQ Calls', 'nav_title': 'Non-Qualified Calls',
                            'tab_icon': 'non-qualified-calls', 'tab_color': '#B0234F', 'docs': ('non-qualified-calls.md',)},
    'reporting': {'css': 'module-tab-report-jobs', 'href': '/reporting', 'title': 'Reporting', 'short_title': 'Reporting',
                  'nav_title': 'Reporting', 'tab_icon': 'reporting', 'tab_color': '#2E8C58', 'docs': ('reporting.md',)},
    'builders': {'css': 'module-tab-chart-builder', 'href': '/chart-builder', 'title': 'Builders', 'short_title': 'Builders',
                 'nav_title': 'Builders', 'tab_icon': 'builders', 'tab_color': '#B85B20',
                 'docs': ('chart-builder.md', 'query-builder.md')},
}

# Icons a main tab can show before its title (24 x 24, drawn with lines).
TAB_ICONS: dict[str, dict[str, str]] = {
    'workspace': {'label': 'Folder (Workspace)',
                  'd': '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/><path d="M3 10.5h18"/>'},
    'datasets-analysis': {'label': 'Database search (CDR Analysis)',
                          'd': '<ellipse cx="10" cy="5.5" rx="6" ry="2.5"/><path d="M4 5.5v9c0 1.4 2.7 2.5 6 2.5M16 5.5v4M4 10c0 1.4 2.7 2.5 6 2.5"/><circle cx="17" cy="15.5" r="3"/><path d="m19.2 17.7 2.3 2.3"/>'},
    'e2e-dashboards': {'label': 'Dashboard (E2E Dashboards)',
                       'd': '<rect x="3" y="3" width="8" height="10" rx="1.5"/><rect x="13" y="3" width="8" height="6" rx="1.5"/><rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="15" width="8" height="6" rx="1.5"/>'},
    'reporting-old': {'label': 'Report page (Reporting (old))',
                      'd': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 17v-3M12 17v-6M15 17v-4"/>'},
    'scoring': {'label': 'Trophy (Scoring)',
                'd': '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5.5a3 3 0 0 0 3 4M16 6h2.5a3 3 0 0 1-3 4M12 13v4M8.5 21h7M10 17h4v4h-4z"/>'},
    'network-insights': {'label': 'Antenna (Network Insights)',
                         'd': '<circle cx="12" cy="9" r="1.6"/><path d="M12 10.6V21M9 21l3-9 3 9M8.6 5.6a4.8 4.8 0 0 0 0 6.8M15.4 5.6a4.8 4.8 0 0 1 0 6.8M5.8 2.8a8.8 8.8 0 0 0 0 12.4M18.2 2.8a8.8 8.8 0 0 1 0 12.4"/>'},
    'non-qualified-calls': {'label': 'Failed call (Non-Qualified Calls)',
                            'd': '<path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/><path d="m15 3 6 6M21 3l-6 6"/>'},
    'reporting': {'label': 'Scheduled mail (Reporting)',
                  'd': '<rect x="2.5" y="5" width="14" height="11" rx="2"/><path d="m3 6.5 6.5 5 6.5-5"/><circle cx="17.5" cy="16.5" r="4"/><path d="M17.5 14.6v2l1.3 1"/>'},
    'builders': {'label': 'Wrench (Builders)',
                 'd': '<path d="M14.7 6.3a4 4 0 0 0-5.3 5.3L3.5 17.5a2 2 0 0 0 2.9 2.9l5.9-5.9a4 4 0 0 0 5.3-5.3l-2.5 2.5-2.4-.5-.5-2.4z"/>'},
    'bar-chart': {'label': 'Bar chart', 'd': '<path d="M4 20h16M7 16v-5M12 16V6M17 16v-8"/>'},
    'line-chart': {'label': 'Line chart', 'd': '<path d="M4 4v16h16"/><path d="m7 15 4-5 3 3 5-6"/>'},
    'pie-chart': {'label': 'Pie chart', 'd': '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>'},
    'gauge': {'label': 'Gauge', 'd': '<path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 17 4-5M12 17h.01"/>'},
    'map': {'label': 'Map', 'd': '<path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>'},
    'globe': {'label': 'Globe', 'd': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3"/>'},
    'signal': {'label': 'Signal bars', 'd': '<path d="M5 20v-3M10 20v-7M15 20V9M20 20V4"/>'},
    'target': {'label': 'Target', 'd': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>'},
    'layers': {'label': 'Layers', 'd': '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>'},
    'table': {'label': 'Table', 'd': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 10v10"/>'},
    'document': {'label': 'Document', 'd': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'},
    'slides': {'label': 'Slides', 'd': '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>'},
    'calendar': {'label': 'Calendar', 'd': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'},
    'users': {'label': 'People', 'd': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6 6 0 0 1 3.5 6"/>'},
    'bell': {'label': 'Bell', 'd': '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>'},
    'flag': {'label': 'Flag', 'd': '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>'},
    'star': {'label': 'Star', 'd': '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>'},
}

MODULE_ORDER = {module: index for index, (module, _name) in enumerate(MAIN_MODULES)}

# Icons and colours of the administrative and documentation tabs, also shown
# in the Modules menu and the Help navigation.
ADMINISTRATIVE_ICONS: dict[str, dict[str, str]] = {
    'readme': {'d': '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5M8 8h8M8 12h6"/>', 'color': '#5A6773'},
    'changelog': {'d': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 'color': '#5A6773'},
    'help': {'d': '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.9M12 17.2h.01"/>', 'color': '#5A6773'},
    'app-logs': {'d': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>', 'color': '#B07A12'},
    'config': {'d': '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>', 'color': '#08736D'},
    'admin': {'d': '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>', 'color': '#B84343'},
}
ADMINISTRATIVE_HELP_ICONS = {'app-logs.md': 'app-logs', 'app-config.md': 'config', 'workspace-config.md': 'config',
                             'administrator-config.md': 'admin'}
# Icons of the General and Reference Help chapters, in the colour of Readme and Changelog.
DOCUMENT_HELP_ICONS: dict[str, str] = {
    'overview.md': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    'technical-considerations.md': '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 10h4v4h-4zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    'configuration.md': '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    'docker-deployment.md': '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    'web-interface.md': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    'project-structure.md': '<path d="M4 3v15h7M4 8h7"/><rect x="11" y="5" width="9" height="6" rx="1.5"/><rect x="11" y="15" width="9" height="6" rx="1.5"/>',
    'roadmap.md': '<path d="m9 4-6 2v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
}

STAGE_COLOURS = {'alpha': '#D7263D', 'beta': '#FFD60A', 'new': '#2563EB', 'stable': '#1F8A4C'}

# Stable modules carry no label text: only the modules still in development are labelled.
DEFAULT_MODULE_LABELS: dict[str, dict[str, str]] = {
    'workspace': {'text': '', 'color': STAGE_COLOURS['stable'], 'icon': '', 'icon_color': '#FFFFFF'},
    'datasets-analysis': {'text': '', 'color': STAGE_COLOURS['stable'], 'icon': '', 'icon_color': '#FFFFFF'},
    'network-insights': {'text': 'ALPHA', 'color': STAGE_COLOURS['alpha'], 'icon': '', 'icon_color': '#FFFFFF'},
    'e2e-dashboards': {'text': '', 'color': STAGE_COLOURS['stable'], 'icon': '', 'icon_color': '#FFFFFF'},
    'scoring': {'text': 'NEW', 'color': STAGE_COLOURS['new'], 'icon': 'star', 'icon_color': '#FFD60A'},
    'non-qualified-calls': {'text': 'ALPHA', 'color': STAGE_COLOURS['alpha'], 'icon': '', 'icon_color': '#FFFFFF'},
    'reporting': {'text': 'BETA', 'color': STAGE_COLOURS['beta'], 'icon': '', 'icon_color': '#3D2A00'},
    'reporting-old': {'text': '', 'color': '#6B7785', 'icon': '', 'icon_color': '#FFFFFF'},
    'builders': {'text': 'BETA', 'color': STAGE_COLOURS['beta'], 'icon': '', 'icon_color': '#3D2A00'},
}

# Predefined icons drawn in a 10 x 10 box at the left of the label (x 3–13, y 2–12).
ICONS: dict[str, dict[str, str]] = {
    'star': {'label': 'Star', 'mode': 'fill',
             'd': 'M8.00 2.60 L9.12 5.66 L12.37 5.78 L9.81 7.79 L10.70 10.92 L8.00 9.10 L5.30 10.92 L6.19 7.79 L3.63 5.78 L6.88 5.66Z'},
    'bolt': {'label': 'Lightning bolt', 'mode': 'fill', 'd': 'M9.4 2.4 L4.4 8.1 L7.6 8.1 L6.4 11.8 L11.4 6.0 L8.2 6.0 Z'},
    'check': {'label': 'Check mark', 'mode': 'stroke', 'd': 'M4.0 7.4 L6.7 10.0 L12.0 4.2'},
    'flask': {'label': 'Flask (experimental)', 'mode': 'stroke',
              'd': 'M6.6 3.0 L6.6 6.1 L4.1 10.4 Q3.8 11.3 4.7 11.3 L11.3 11.3 Q12.2 11.3 11.9 10.4 L9.4 6.1 L9.4 3.0 M5.8 3.0 L10.2 3.0'},
    'warning': {'label': 'Warning', 'mode': 'stroke', 'd': 'M8.0 2.9 L12.4 11.1 L3.6 11.1 Z M8.0 6.0 L8.0 8.3 M8.0 9.6 L8.0 9.7'},
    'dot': {'label': 'Dot', 'mode': 'fill', 'd': 'M8.0 4.4 A2.6 2.6 0 1 1 7.99 4.4 Z'},
    'sparkle': {'label': 'Sparkle', 'mode': 'fill', 'd': 'M8 2.4 Q8.7 6.3 12.6 7 Q8.7 7.7 8 11.6 Q7.3 7.7 3.4 7 Q7.3 6.3 8 2.4 Z'},
    'rocket': {'label': 'Rocket', 'mode': 'stroke',
               'd': 'M8 2.6 C10.4 4.2 10.8 7 10 9.6 L6 9.6 C5.2 7 5.6 4.2 8 2.6 Z M6 8.4 L4.4 10.8 L6.2 10.4 M10 8.4 L11.6 10.8 L9.8 10.4 M8 6.1 L8 6.2'},
    'flame': {'label': 'Flame', 'mode': 'fill',
              'd': 'M8 2.4 C9 4.4 11.4 5.6 11.4 8.4 C11.4 10.6 9.8 11.8 8 11.8 C6.2 11.8 4.6 10.6 4.6 8.4 C4.6 6.8 5.6 5.8 6.4 5.2 C6.4 6.6 7 7.4 7.8 7.6 C7.4 5.8 7.6 3.8 8 2.4 Z'},
    'trending': {'label': 'Trending up', 'mode': 'stroke', 'd': 'M3.6 10.4 L6.6 7.4 L8.6 9.2 L12.2 4.8 M9.6 4.6 L12.4 4.6 L12.4 7.4'},
    'heart': {'label': 'Heart', 'mode': 'fill',
              'd': 'M8 11.4 C3.6 8.6 3.4 5.8 4.6 4.4 C5.8 3 7.4 3.6 8 4.8 C8.6 3.6 10.2 3 11.4 4.4 C12.6 5.8 12.4 8.6 8 11.4 Z'},
    'crown': {'label': 'Crown', 'mode': 'fill', 'd': 'M3.6 10.6 L3.4 4.8 L6 7.2 L8 3.6 L10 7.2 L12.6 4.8 L12.4 10.6 Z'},
    'shield': {'label': 'Shield', 'mode': 'stroke', 'd': 'M8 2.6 L12 4 L12 7 C12 9.4 10.2 11 8 11.8 C5.8 11 4 9.4 4 7 L4 4 Z'},
    'lock': {'label': 'Lock', 'mode': 'stroke', 'd': 'M5 6.6 L11 6.6 L11 11.4 L5 11.4 Z M6.4 6.6 L6.4 5 A1.6 1.6 0 0 1 9.6 5 L9.6 6.6'},
    'clock': {'label': 'Clock (coming soon)', 'mode': 'stroke', 'd': 'M8 2.8 A4.2 4.2 0 1 1 7.99 2.8 Z M8 4.6 L8 7.2 L9.8 8.2'},
    'wrench': {'label': 'Wrench (maintenance)', 'mode': 'stroke',
               'd': 'M12 4.6 A2.4 2.4 0 0 1 8.8 6.8 L4.6 11 L3.4 9.8 L7.6 5.6 A2.4 2.4 0 0 1 9.8 2.4 L8.6 3.6 L9 5 L10.4 5.4 Z'},
    'bug': {'label': 'Bug', 'mode': 'stroke',
            'd': 'M6.2 5.4 A1.8 1.8 0 0 1 9.8 5.4 Z M5.6 6.4 L10.4 6.4 L10.4 9 A2.4 2.4 0 0 1 5.6 9 Z M8 6.4 L8 11.4 M5.6 7.6 L3.8 7 M10.4 7.6 L12.2 7 M5.6 9.4 L3.8 10.2 M10.4 9.4 L12.2 10.2'},
    'info': {'label': 'Information', 'mode': 'stroke', 'd': 'M8 2.8 A4.2 4.2 0 1 1 7.99 2.8 Z M8 6.6 L8 9.6 M8 4.8 L8 4.9'},
    'cross': {'label': 'Cross', 'mode': 'stroke', 'd': 'M4.6 3.6 L11.4 10.4 M11.4 3.6 L4.6 10.4'},
}

_COLOUR = re.compile(r'#[0-9A-Fa-f]{6}')


def _colour(value: object, fallback: str) -> str:
    text = str(value or '').strip()
    return text.upper() if _COLOUR.fullmatch(text) else fallback


def _position(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def normalize_module_labels(raw: object) -> dict[str, dict[str, Any]]:
    """Every main module with a valid tab and label, falling back to the defaults field by field.

    Modules are returned in tab order, and their ``position`` is renumbered from 0.
    """
    stored = raw if isinstance(raw, dict) else {}
    labels = {}
    for index, (module, _name) in enumerate(MAIN_MODULES):
        default = {**DEFAULT_MODULE_LABELS[module], **MODULE_TABS[module]}
        entry = stored.get(module) if isinstance(stored.get(module), dict) else {}
        text = str(entry.get('text', default['text']) or '').strip()[:MAX_LABEL_LENGTH]
        icon = str(entry.get('icon', default['icon']) or '').strip()
        title = str(entry.get('title') or '').strip()[:MAX_TITLE_LENGTH] or default['title']
        short_title = str(entry.get('short_title') or '').strip()[:MAX_SHORT_TITLE_LENGTH]
        tab_icon = str(entry.get('tab_icon', default['tab_icon']) or '').strip()
        labels[module] = {
            'text': text,
            'color': _colour(entry.get('color'), default['color']),
            'icon': icon if icon in ICONS else '',
            'icon_color': _colour(entry.get('icon_color'), default['icon_color']),
            'title': title,
            # A title changed without a short title keeps it on narrow windows too.
            'short_title': short_title or (default['short_title'] if title == default['title'] else title),
            'tab_icon': tab_icon if tab_icon in TAB_ICONS else '',
            'tab_color': _colour(entry.get('tab_color'), default['tab_color']),
            'position': _position(entry.get('position'), index),
        }
    order = sorted(labels, key=lambda module: (labels[module]['position'], MODULE_ORDER[module]))
    return {module: {**labels[module], 'position': position} for position, module in enumerate(order)}


def load_module_labels(repository: Any) -> dict[str, dict[str, str]]:
    try:
        return normalize_module_labels(json.loads(repository.get_application_state(MODULE_LABELS_STATE_KEY) or '{}'))
    except (TypeError, ValueError):
        return normalize_module_labels({})


def module_tabs(labels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The main tabs in their order, with what the navigation draws for each one."""
    tabs = []
    for module, label in labels.items():
        default = MODULE_TABS[module]
        custom_colour = label['tab_color'] != default['tab_color']
        tabs.append({
            'key': module, 'css': default['css'], 'href': default['href'],
            'title': label['title'], 'short_title': label['short_title'],
            'nav_title': default['nav_title'] if label['title'] == default['title'] else label['title'],
            'icon_path': TAB_ICONS[label['tab_icon']]['d'] if label['tab_icon'] else '',
            'tab_color': label['tab_color'],
            # A colour other than the module palette replaces its accent and selected gradient.
            'colour_style': f"--tab-accent: {label['tab_color']}" if custom_colour else '',
        })
    return tabs


def ordered_help_documents(documents: tuple[str, ...] | list[str], labels: dict[str, dict[str, Any]]) -> list[str]:
    """Help navigation with the chapters of the main modules in tab order."""
    chapters = [document for module in labels for document in MODULE_TABS[module]['docs']]
    moved = set(chapters)
    ordered = [document for document in documents if document not in moved]
    first = next((index for index, document in enumerate(documents) if document in moved), len(documents))
    start = len([document for document in documents[:first] if document not in moved])
    return ordered[:start] + [document for document in chapters if document in documents] + ordered[start:]


def help_chapter_icons(labels: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Icon and colour of each Help chapter: its module tab, or a document icon for General and Reference."""
    icons = {document: {'icon': icon, 'icon_color': ADMINISTRATIVE_ICONS['readme']['color']}
             for document, icon in DOCUMENT_HELP_ICONS.items()}
    icons |= {document: {'icon': ADMINISTRATIVE_ICONS[icon]['d'], 'icon_color': ADMINISTRATIVE_ICONS[icon]['color']}
              for document, icon in ADMINISTRATIVE_HELP_ICONS.items()}
    return icons | {document: {'icon': TAB_ICONS[label['tab_icon']]['d'], 'icon_color': label['tab_color']}
                    for module, label in labels.items() if label['tab_icon'] for document in MODULE_TABS[module]['docs']}


def renamed_help_chapters(labels: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Help chapters of renamed modules, with the title they take in the Help navigation."""
    return {MODULE_TABS[module]['docs'][0]: label['title'] for module, label in labels.items()
            if label['title'] != MODULE_TABS[module]['title'] and len(MODULE_TABS[module]['docs']) == 1}


def rename_modules_in_help(content: str, document: str, labels: dict[str, dict[str, Any]]) -> str:
    """Help text with renamed modules under their new title.

    The chapter of a renamed module takes the new title as its heading, and every
    document names the module with its new title outside section headings, which
    links reach by their anchor. Titles of one word (Workspace, Reporting,
    Builders) are also ordinary words of the Help, so the Help marks the
    mentions of those modules as a link to their chapter or in bold
    (``[Reporting](reporting.md)`` or ``**Reporting**``) and only those change.
    """
    for module, label in labels.items():
        default = MODULE_TABS[module]['title']
        if label['title'] == default:
            continue
        if document in MODULE_TABS[module]['docs'] and len(MODULE_TABS[module]['docs']) == 1:
            content = re.sub(r'\A(\s*#\s+).*', lambda match: match.group(1) + label['title'], content, count=1)
        names = '|'.join(re.escape(name) for name in dict.fromkeys([default, MODULE_TABS[module]['nav_title']]))
        for document_name in MODULE_TABS[module]['docs']:
            content = re.sub(rf'\[(?:{names})\]\({re.escape(document_name)}', lambda _match: f"[{label['title']}]({document_name}", content)
        content = re.sub(rf'\*\*(?:{names})\*\*', lambda _match: f"**{label['title']}**", content)
        if ' ' in default:
            # Section headings keep their name: links point at them by their anchor.
            pattern = re.compile(rf'(?<![\w/-]){re.escape(default)}(?![\w-])')
            content = '\n'.join(line if line.lstrip().startswith('#') else pattern.sub(lambda _match: label['title'], line)
                                 for line in content.split('\n'))
    return content


def _ink(colour: str) -> str:
    """White text on colours where it reads well (contrast of at least 3:1), dark text on light colours."""
    red, green, blue = (int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5))
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in (red, green, blue)]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return '#FFFFFF' if 1.05 / (luminance + 0.05) >= 3 else '#2B2100'


def module_label_badges(labels: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """What each module tab draws: text, colours, icon and width in label units (14 units high)."""
    badges = {}
    for module, label in labels.items():
        if not label['text']:
            continue
        icon = ICONS.get(label['icon'])
        # The icon spans x 3–13; the text starts after a small gap.
        text_start = 16 if icon else 4
        width = text_start + round(6.2 * len(label['text'])) + 4
        badges[module] = {
            **label,
            'ink': _ink(label['color']),
            'width': width,
            'text_x': (text_start + width - 4) / 2,
            'icon_path': icon['d'] if icon else '',
            'icon_mode': icon['mode'] if icon else '',
        }
    return badges
