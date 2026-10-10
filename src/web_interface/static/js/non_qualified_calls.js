/* Non-Qualified Calls: executive summary, drill-down table, follow-up and shared comments. */
(() => {
  'use strict';

  const root = document.getElementById('non-qualified-calls');
  if (!root || !document.getElementById('nq-table')) return;

  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const SERVICE_LABELS = {voice: 'Voice', speech: 'Speech', data: 'Data'};
  const FIELD_LABELS = {
    service: 'Service', campaign: 'Campaign', operator: 'Operator', operator_vendor: 'Operator_Vendor', vendor_operator: 'Vendor_Operator', vendor: 'Vendor',
    region: 'Region', cluster: 'Cluster', city: 'City', dataset_id: 'CDR', join_id: 'Join ID',
    technology: 'Technology', test_name: 'Test Name', result: 'Result', failure_classification: 'Failure Classification',
    failure_category: 'Failure Category', status: 'Status', team: 'Team', assignee: 'Assignee', datasets: 'CDR',
    root_domain: 'Root Domain', root_category: 'Root Category', root_cause: 'Root Cause', status_mode: 'Status Set',
    nr_mode: 'NR Mode', call_type: 'Call Type', period: 'Period',
    age: 'Age of Open Calls', root_pair: 'Root Domain · Cause', effective_domain: 'Root Domain (with suggestions)',
    effective_cause: 'Root Domain · Cause (with suggestions)', node: 'eNB / gNB', state: 'Follow-up', rca_state: 'Root Cause',
    version: 'CDR Version',
  };
  // How the CDRs see a call; "current" is the latest version with nothing to tell.
  const VERSION_HINTS = {
    changed: 'Its result or failure is different in another CDR',
    newer: 'A more recent CDR that is not chosen in the CDRs filter has this call',
    not_in_final: 'Only in Weekly or Daily CDRs, while a Final CDR covers its campaign',
    qualified: 'Completed in a more recent CDR',
  };
  const STATE_LABELS = {closed: 'Closed', attended: 'Attended', not_attended: 'Not attended', with_team: 'With team',
    assigned: 'Assigned', commented: 'Commented', labelled: 'With a root cause', suggested: 'Suggested root cause',
    identified: 'RCA identified', not_identified: 'RCA not identified'};
  // Filters set by clicking the Progress View and the Root Cause Analysis; they have no select of their own.
  const EXTRA_FILTERS = ['nr_mode', 'call_type', 'period', 'age', 'root_pair', 'effective_domain', 'effective_cause', 'node',
    'state', 'rca_state'];
  const HISTORY_LABELS = {status: 'Status', status_auto: 'Status (automatic)', status_mode: 'Status Set', team: 'Team',
    assignee: 'Assignee', root_domain: 'Root Domain', root_category: 'Root Category', root_cause: 'Root Cause'};
  // The label of a changed field: a follow-up field or a catalog field ("field:key").
  const historyLabel = (field) => (field.startsWith('field:')
    ? (state.fields.find((item) => item.key === field.slice(6))?.label || field.slice(6)) : (HISTORY_LABELS[field] || field));
  const NOT_CLASSIFIED = 'Not classified';
  const NO_CAUSE = 'No cause';
  // Whether the NQ Call Status follows the Status Rules or was chosen by hand.
  const STATUS_MODE_LABELS = {auto: 'Automatic', manual: 'By hand'};
  // The status selects offer this value to give the status back to the Status Rules.
  const AUTO_STATUS = '__auto__';
  // Where a catalog field takes its value from, as a short tag.
  const SOURCE_TAGS = {user: 'Analyst', tracking: 'Follow-up', cdr: 'CDR', rca: 'RCA script', derived: 'Derived'};
  const CONFIDENCE_LABELS = {high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence'};
  // The sections whose first list field is a phase of the follow-up.
  const PHASE_SECTIONS = ['analysis', 'implementation', 'planning'];
  // Campaigns as the workspace Campaign Maps show them (campaign_labels.js); filters keep the full value.
  const campaignLabel = (value) => (globalThis.campaignLabel ? globalThis.campaignLabel(value) : String(value ?? ''));
  // A field value travels in the bulk select as "key||value".
  const ROOT_SEPARATOR = '||';
  const REFRESH_INTERVAL_MS = 60000;

  const state = {
    options: {statuses: [], teams: []}, rootCauses: {domains: [], categories: [], causes: [], require_to_close: false}, users: [],
    user: {username: '', can_edit: false, can_moderate: false},
    unassigned: '__unassigned__', datasets: [], mainCities: [], sort: 'start_time', direction: 'desc', page: 1, pageSize: 50,
    result: null, selected: new Set(), detail: null, requestToken: 0, busy: false, extraFilters: {}, stale: new Set(), view: 'calls',
    fields: [], fieldTypes: {}, tableColumns: {builtin: [], cdr: []}, optionalColumns: {}, cdrColumns: [], versionLabels: {},
    rateService: '', sections: [], statusRules: [], conditionFields: {}, ruleOperators: {}, fieldSources: {}, trackingRefs: {},
    rcaRefs: {}, callFields: [], rcaResults: {}, rcaSources: {}, matrixSource: 'script',
  };

  // -- helpers --------------------------------------------------------------
  const api = async (url, init = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...init,
      headers: init.body ? {'Content-Type': 'application/json', ...(init.headers || {})} : init.headers});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof payload.detail === 'string' ? payload.detail : 'The request failed.');
      error.status = response.status;
      throw error;
    }
    return payload;
  };
  const toast = (message, tone = 'done') => {
    const element = node('div', message, `nq-toast is-${tone}`);
    element.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    document.body.append(element);
    window.setTimeout(() => element.classList.add('is-leaving'), 3600);
    window.setTimeout(() => element.remove(), 4000);
  };
  const debounce = (callback, delay) => {
    let timer = null;
    return (...args) => { window.clearTimeout(timer); timer = window.setTimeout(() => callback(...args), delay); };
  };
  const parseTime = (value) => {
    if (!value) return null;
    const parsed = new Date(String(value).replace(' ', 'T'));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };
  const exactTime = (value) => {
    const parsed = parseTime(value);
    return parsed ? parsed.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'}) : (value || '—');
  };
  const relativeTime = (value) => {
    const parsed = parseTime(value);
    if (!parsed) return value || '';
    const seconds = Math.round((Date.now() - parsed.getTime()) / 1000);
    if (seconds < 45) return 'just now';
    if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
    if (seconds < 7 * 86400) return `${Math.round(seconds / 86400)} d ago`;
    return parsed.toLocaleDateString(undefined, {dateStyle: 'medium'});
  };
  const cdrTime = (value) => (value ? String(value).replace('T', ' ').replace(/\.\d+$/, '') : '—');
  const percent = (part, total) => (total ? `${Math.round((part / total) * 100)}%` : '0%');
  const number = (value) => Number(value || 0).toLocaleString();
  // Readable text on any option colour.
  const contrastText = (hex) => {
    const match = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!match) return '#fff';
    const value = parseInt(match[1], 16);
    const channel = (shift) => {
      const c = ((value >> shift) & 255) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const luminance = 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0);
    return luminance > 0.45 ? '#2a1a20' : '#fff';
  };
  // A Root Category or Root Cause of the catalog, by name.
  const rootItem = (kind, name) => (name ? (kind === 'root_category' ? state.rootCauses.categories : state.rootCauses.causes)
    .find((item) => item.name.toLowerCase() === String(name).toLowerCase()) : null);
  const domainColor = (name) => state.rootCauses.domains.find((item) => item.name === name)?.color || '';
  // Root categories or causes grouped by domain, in the catalog order; a preferred domain first, those without one last.
  const rootGroups = (items, preferred = '') => {
    const names = state.rootCauses.domains.map((domain) => domain.name);
    const order = [...(preferred && names.includes(preferred) ? [preferred] : []), ...names.filter((name) => name !== preferred), ''];
    return order.map((domain) => [domain, items.filter((item) => (names.includes(item.domain) ? item.domain : '') === domain)])
      .filter(([, group]) => group.length);
  };
  // Root categories and causes take the colour of their domain.
  const optionColor = (kind, name) => {
    if (kind === 'root_domain') return domainColor(name);
    if (kind === 'root_category' || kind === 'root_cause') return rootItem(kind, name)?.color || '';
    const list = kind === 'status' ? state.options.statuses : state.options.teams;
    return list.find((item) => item.name === name)?.color || '';
  };
  const sectionOf = (key) => state.sections.find((section) => section.key === key) || {key, label: key, color: '#7b8790'};
  const paintPill = (element, color) => {
    if (color) {
      element.style.setProperty('--nq-pill', color);
      element.style.setProperty('--nq-pill-text', contrastText(color));
      element.classList.add('is-colored');
    } else {
      element.style.removeProperty('--nq-pill');
      element.style.removeProperty('--nq-pill-text');
      element.classList.remove('is-colored');
    }
  };
  // A root cause is outlined in the colour of its domain, so it reads apart from its category.
  const outlinePill = (element, color) => {
    paintPill(element, '');
    if (color) element.style.setProperty('--nq-outline', color);
    else element.style.removeProperty('--nq-outline');
    element.classList.toggle('is-outlined', Boolean(color));
  };
  const pill = (kind, name, emptyLabel = 'Unassigned') => {
    const element = node('span', name || emptyLabel, `nq-pill nq-pill-${kind}`);
    if (kind === 'root_cause') outlinePill(element, optionColor(kind, name));
    else paintPill(element, kind === 'assignee' ? '' : optionColor(kind, name));
    if (!name) element.classList.add('is-empty');
    return element;
  };
  // A small tag in the colour of a section (or of a source).
  const sectionTag = (key) => {
    const section = sectionOf(key);
    const tag = node('span', section.label, 'nq-section-tag');
    tag.style.setProperty('--nq-section', section.color);
    return tag;
  };
  const initials = (name) => String(name || '?').split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
  const avatar = (name) => {
    let hash = 0;
    for (const character of String(name || '')) hash = (hash * 31 + character.charCodeAt(0)) % 360;
    const element = node('span', initials(name), 'nq-avatar');
    element.style.background = `hsl(${hash} 52% 42%)`;
    element.title = name;
    return element;
  };
  const resultClass = (result) => {
    const value = String(result || '').toLowerCase();
    return ['failed', 'dropped', 'cutoff'].includes(value) ? `is-${value}` : 'is-other';
  };
  const canChangeComment = (comment) => state.user.can_edit && !comment.deleted_at
    && (state.user.can_moderate || comment.created_by.toLowerCase() === state.user.username.toLowerCase());

  // -- filters --------------------------------------------------------------
  // The list and Yes / No fields chosen among their values: entered by the analysts or derived from the call.
  const filterableFields = () => state.fields.filter((field) => ['list', 'yes_no'].includes(field.type)
    && ['user', 'derived'].includes(field.source));
  const filterSelects = () => [...root.querySelectorAll('[data-nq-filter]')];
  const fillSelect = (select, entries) => {
    const previous = new Set([...select.selectedOptions].map((option) => option.value));
    select.dataset.multiselectNoValuesLabel = 'No values available';
    select.replaceChildren(...entries.map(([value, label]) => {
      const option = node('option', label);
      option.value = value;
      option.selected = previous.has(value);
      return option;
    }));
    select.dispatchEvent(new Event('multiselect:options-updated'));
  };
  const fillFilters = (payload) => {
    const values = payload.filter_options || {};
    const unassigned = [state.unassigned, 'Unassigned'];
    const entries = {
      datasets: state.datasets.map((dataset) => [String(dataset.id), `${dataset.name} (${number(dataset.calls)})`]),
      service: ['voice', 'speech', 'data'].filter((value) => (values.service || []).includes(value)).map((value) => [value, SERVICE_LABELS[value]]),
      status: state.options.statuses.map((item) => [item.name, item.name]),
      team: [unassigned, ...state.options.teams.map((item) => [item.name, item.name])],
      assignee: [unassigned, ...[...new Set([...(values.assignee || []), ...state.users])].sort((a, b) => a.localeCompare(b)).map((name) => [name, name])],
      root_domain: [[state.unassigned, NOT_CLASSIFIED], ...state.rootCauses.domains.map((item) => [item.name, item.name])],
      root_category: [[state.unassigned, NOT_CLASSIFIED], ...state.rootCauses.categories.map((item) => [item.name, item.name])],
      root_cause: [[state.unassigned, NO_CAUSE], ...state.rootCauses.causes.map((item) => [item.name, item.name])],
      status_mode: Object.entries(STATUS_MODE_LABELS),
      version: Object.entries(state.versionLabels),
    };
    // A filter for every list and Yes / No field of the Analysis Center, after the others.
    const fieldHost = $('nq-field-filters');
    const filterable = filterableFields();
    const present = new Set(filterable.map((field) => `field:${field.key}`));
    fieldHost.querySelectorAll('[data-nq-filter]').forEach((select) => {
      if (!present.has(select.dataset.nqFilter)) select.closest('label').remove();
    });
    filterable.forEach((field) => {
      const name = `field:${field.key}`;
      entries[name] = [[state.unassigned, 'Empty'], ...(field.type === 'yes_no' ? ['Yes', 'No'] : field.options.map((option) => option.name))
        .map((value) => (Array.isArray(value) ? value : [value, value]))];
      if (fieldHost.querySelector(`[data-nq-filter="${CSS.escape(name)}"]`)) return;
      const label = node('label', field.label);
      const select = node('select');
      select.multiple = true;
      select.size = 1;
      select.dataset.nqFilter = name;
      select.dataset.multiselectNoValuesLabel = 'No values available';
      select.dataset.multiselectEmptyLabel = 'All values';
      select.setAttribute('aria-label', field.label);
      label.append(select);
      fieldHost.append(label);
    });
    fieldHost.hidden = !filterable.length;
    $('nq-field-filters-title').hidden = fieldHost.hidden;
    // A filter for every optional and CDR column of the table (Region, Cluster and CDR have theirs).
    const columnHost = $('nq-column-filters');
    const cdrColumnHost = $('nq-cdr-column-filters');
    const columns = columnFilters();
    const wanted = new Set(columns.map((column) => column.filter));
    [columnHost, cdrColumnHost].forEach((host) => host.querySelectorAll('[data-nq-filter]').forEach((select) => {
      if (!wanted.has(select.dataset.nqFilter)) select.closest('label').remove();
    }));
    columns.forEach((column) => {
      entries[column.filter] = [[state.unassigned, 'Empty'], ...(values[column.filter] || []).map((value) => [value, value])];
      // CDR columns add no filter to the panel: they filter from their header only.
      const host = column.filter.startsWith('column:cdr:') ? cdrColumnHost : columnHost;
      if (host.querySelector(`[data-nq-filter="${CSS.escape(column.filter)}"]`)) return;
      const label = node('label', column.label);
      const select = node('select');
      select.multiple = true;
      select.size = 1;
      select.dataset.nqFilter = column.filter;
      select.dataset.multiselectNoValuesLabel = 'No values available';
      select.dataset.multiselectEmptyLabel = 'All values';
      select.setAttribute('aria-label', column.label);
      label.append(select);
      host.append(label);
    });
    columnHost.hidden = !columnHost.querySelector('[data-nq-filter]');
    $('nq-column-filters-title').hidden = columnHost.hidden;
    // New selects get the checkbox menu of every multi-select of the page.
    if (typeof globalThis.setupCustomMultiSelects === 'function') globalThis.setupCustomMultiSelects();
    filterSelects().forEach((select) => {
      const field = select.dataset.nqFilter;
      if (field === 'city') {
        const present = new Set((values.city || []).map((value) => value.toLocaleLowerCase()));
        select.dataset.multiselectPresetValues = state.mainCities.filter((city) => present.has(city.toLocaleLowerCase())).join('|');
      }
      fillSelect(select, entries[field] || (values[field] || []).map((value) => [value, field === 'campaign' ? campaignLabel(value) : value]));
    });
  };
  const currentFilters = () => {
    const filters = {};
    filterSelects().forEach((select) => {
      const enabled = [...select.options];
      const chosen = enabled.filter((option) => option.selected).map((option) => option.value);
      // Every value or none means no restriction.
      if (!chosen.length || chosen.length >= enabled.length) return;
      const field = select.dataset.nqFilter;
      // Analysis fields travel together: {fields: {key: [values]}}; so do the table columns: {columns: {key: [values]}}.
      if (field.startsWith('field:')) (filters.fields ||= {})[field.slice(6)] = chosen;
      else if (field.startsWith('column:')) (filters.columns ||= {})[field.slice(7)] = chosen;
      else filters[field] = chosen;
    });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { if (box.checked) filters[box.dataset.nqFlag] = true; });
    Object.entries(state.extraFilters).forEach(([field, values]) => { if (values.length) filters[field] = [...values]; });
    // The typed filters (Join ID): values separated by commas, spaces or lines.
    root.querySelectorAll('[data-nq-typed-filter]').forEach((input) => {
      const values = [...new Set(input.value.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean))];
      if (values.length) filters[input.dataset.nqTypedFilter] = values;
    });
    const search = $('nq-search').value.trim();
    if (search) filters.search = search;
    return filters;
  };
  // The selection is shared by every user of the workspace and restored in every session.
  // The values of a filter, including the analysis fields ("field:key").
  const filterValues = (filters, field) => (field.startsWith('field:') ? (filters.fields || {})[field.slice(6)]
    : field.startsWith('column:') ? (filters.columns || {})[field.slice(7)] : filters[field]);
  const applySavedFilters = (saved) => {
    filterSelects().forEach((select) => {
      const values = new Set(filterValues(saved, select.dataset.nqFilter) || []);
      [...select.options].forEach((option) => { option.selected = values.has(option.value); });
      select.dispatchEvent(new Event('multiselect:options-updated'));
    });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { box.checked = saved[box.dataset.nqFlag] === true; });
    state.extraFilters = Object.fromEntries(EXTRA_FILTERS.filter((field) => (saved[field] || []).length).map((field) => [field, [...saved[field]]]));
    root.querySelectorAll('[data-nq-typed-filter]').forEach((input) => { input.value = (saved[input.dataset.nqTypedFilter] || []).join(', '); });
    $('nq-search').value = saved.search || '';
    state.savedFilters = JSON.stringify(currentFilters());
  };
  const saveFilters = debounce((filters) => {
    const serialized = JSON.stringify(filters);
    if (serialized === state.savedFilters) return;
    state.savedFilters = serialized;
    api('/api/non-qualified-calls/filters', {method: 'PUT', body: JSON.stringify({filters})}).catch(() => { state.savedFilters = null; });
  }, 800);
  const selectOnly = (field, value) => {
    if (field === 'dataset_id') field = 'datasets';
    const select = root.querySelector(`[data-nq-filter="${field}"]`);
    if (!select) return;
    const target = ['team', 'assignee', 'root_domain', 'root_category', 'root_cause'].includes(field) ? (value || state.unassigned) : value;
    const chosen = [...select.selectedOptions].map((option) => option.value);
    const toggleOff = chosen.length === 1 && chosen[0] === target;
    [...select.options].forEach((option) => { option.selected = !toggleOff && option.value === target; });
    select.dispatchEvent(new Event('change', {bubbles: true}));
  };
  // Drill-down from a chart or table value: each [field, value] becomes the only value of its
  // filter (a select of the Filters panel, a flag or one of the extra filters); clicking the
  // same value again removes those filters.
  const drill = (pairs) => {
    const filters = currentFilters();
    const active = pairs.every(([field, value]) => (field === 'open_only' ? filters[field] === true
      : (filterValues(filters, field) || []).length === 1 && filterValues(filters, field)[0] === value));
    pairs.forEach(([field, value]) => {
      if (field === 'open_only') {
        // A pair made only of this flag toggles it; with other values it is only switched on.
        const flag = root.querySelector('[data-nq-flag="open_only"]');
        flag.checked = pairs.length === 1 ? !active : flag.checked || !active;
        return;
      }
      if (EXTRA_FILTERS.includes(field)) {
        if (active) delete state.extraFilters[field]; else state.extraFilters[field] = [value];
        return;
      }
      const select = root.querySelector(`[data-nq-filter="${field}"]`);
      if (!select) return;
      [...select.options].forEach((option) => { option.selected = !active && option.value === value; });
      select.dispatchEvent(new Event('multiselect:options-updated'));
    });
    scheduleLoad();
  };
  const isDrilled = (pairs) => {
    const filters = currentFilters();
    return pairs.every(([field, value]) => (field === 'open_only' ? filters[field] === true
      : (filterValues(filters, field) || []).length === 1 && filterValues(filters, field)[0] === value));
  };
  // The total cards remove the filters their sibling cards set.
  const CARD_FILTERS = ['state', 'rca_state', 'open_only'];
  const clearDrill = (fields) => {
    fields.forEach((field) => {
      if (field === 'open_only') root.querySelector('[data-nq-flag="open_only"]').checked = false;
      else if (EXTRA_FILTERS.includes(field)) delete state.extraFilters[field];
      else {
        const select = root.querySelector(`[data-nq-filter="${field}"]`);
        if (!select) return;
        [...select.options].forEach((option) => { option.selected = false; });
        select.dispatchEvent(new Event('multiselect:options-updated'));
      }
    });
    scheduleLoad();
  };
  // An indicator card that filters the calls (pairs) or clears its panel's card filters (clear).
  const drillCard = (card, {pairs = null, clear = null} = {}) => {
    if (!pairs && !clear) return card;
    card.classList.add('nq-drill-card');
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    const active = pairs ? isDrilled(pairs) : false;
    card.classList.toggle('is-active', active);
    card.title = clear ? 'Show every call of the other filters' : active ? 'Remove this filter' : 'Show only these calls';
    const act = () => (pairs ? drill(pairs) : clearDrill(clear));
    card.addEventListener('click', act);
    card.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); act(); } });
    return card;
  };
  const extraLabel = (field, value) => {
    if (value === state.unassigned) return NOT_CLASSIFIED;
    if (field === 'period') return value.split(':').slice(1).join(':');
    if (field === 'state' || field === 'rca_state') return STATE_LABELS[value] || value;
    return value.replace(/\|\|$/, '').replace('||', ' · ');
  };
  const clearFilter = (field) => {
    if (field === 'search') { $('nq-search').value = ''; scheduleLoad(); return; }
    const typed = root.querySelector(`[data-nq-typed-filter="${field}"]`);
    if (typed) { typed.value = ''; scheduleLoad(); return; }
    if (EXTRA_FILTERS.includes(field)) { delete state.extraFilters[field]; scheduleLoad(); return; }
    const box = root.querySelector(`[data-nq-flag="${field}"]`);
    if (box) { box.checked = false; scheduleLoad(); return; }
    const select = root.querySelector(`[data-nq-filter="${field}"]`);
    if (!select) return;
    [...select.options].forEach((option) => { option.selected = false; });
    select.dispatchEvent(new Event('change', {bubbles: true}));
  };
  // The filters applied, as chips that remove them, at the top of every panel; the NQ Rate panel dims those it ignores.
  const renderActiveFilters = (filters) => {
    const chips = [];
    const flagLabels = {open_only: 'Open calls only', mine: 'Assigned to me', without_comments: 'Without comments'};
    const entries = Object.entries(filters).filter(([field]) => !['fields', 'columns'].includes(field));
    Object.entries(filters.fields || {}).forEach(([key, values]) => entries.push([`field:${key}`, values]));
    Object.entries(filters.columns || {}).forEach(([key, values]) => entries.push([`column:${key}`, values]));
    entries.forEach(([field, value]) => {
      let text;
      if (field === 'search') text = `Search: “${value}”`;
      else if (flagLabels[field]) text = flagLabels[field];
      else {
        const select = root.querySelector(`[data-nq-filter="${field}"]`);
        const labels = value.map((item) => (EXTRA_FILTERS.includes(field) ? extraLabel(field, item)
          : [...(select?.options || [])].find((option) => option.value === item)?.textContent || item));
        const name = field.startsWith('field:') ? historyLabel(field)
          : field.startsWith('column:') ? (select?.getAttribute('aria-label') || field.slice(7)) : (FIELD_LABELS[field] || field);
        text = `${name}: ${labels.length > 3 ? `${labels.slice(0, 3).join(', ')} +${labels.length - 3}` : labels.join(', ')}`;
      }
      chips.push({field, text});
    });
    root.querySelectorAll('[data-nq-active-filters]').forEach((host) => {
      const rates = host.dataset.nqActiveFilters === 'rates';
      host.replaceChildren(...chips.map(({field, text}) => {
        const chip = node('button', text, 'nq-filter-chip');
        chip.type = 'button';
        const ignored = rates && !RATE_FILTER_KEYS.includes(field);
        chip.classList.toggle('is-ignored', ignored);
        chip.title = ignored ? 'This panel does not use this filter\nClick to remove it' : 'Remove this filter';
        chip.append(node('span', '×', 'nq-filter-chip-x'));
        chip.addEventListener('click', () => clearFilter(field));
        return chip;
      }));
      host.hidden = !chips.length;
    });
  };

  // -- summary ----------------------------------------------------------------
  const renderSummary = (result) => {
    const summary = result.summary;
    const cards = [
      ['Non-Qualified Calls', number(summary.total), 'Calls and tests that did not complete', 'total', {clear: CARD_FILTERS}],
      ['Open', number(summary.open), `${percent(summary.open, summary.total)} still under follow-up`, 'open', {pairs: [['open_only', true]]}],
      ['Closed', number(summary.closed), `${percent(summary.closed, summary.total)} resolved or not applicable`, 'closed', {pairs: [['state', 'closed']]}],
      ['Attended', number(summary.attended), `${percent(summary.attended, summary.total)} followed up or commented`, 'attended', {pairs: [['state', 'attended']]}],
      ['With Team', number(summary.with_team), `${percent(summary.with_team, summary.total)} have a responsible team`, 'team', {pairs: [['state', 'with_team']]}],
      ['Commented', number(summary.commented), `${percent(summary.commented, summary.total)} have comments`, 'commented', {pairs: [['state', 'commented']]}],
    ];
    $('nq-kpis').replaceChildren(...cards.map(([label, value, note, kind, drillTarget]) => {
      const card = node('article', undefined, `nq-kpi nq-kpi-${kind}`);
      card.append(node('span', label, 'nq-kpi-label'), node('strong', value), node('span', note, 'nq-kpi-note'));
      return drillCard(card, drillTarget);
    }));
    const filters = currentFilters();
    $('nq-breakdowns').replaceChildren(...result.breakdowns.map((breakdown) => {
      const card = node('section', undefined, 'nq-breakdown');
      card.append(node('h3', breakdown.label));
      const max = Math.max(1, ...breakdown.items.map((item) => item.count));
      if (!breakdown.items.length) card.append(node('p', 'No calls.', 'form-note'));
      breakdown.items.forEach((item, index) => {
        const field = breakdown.field;
        const label = field === 'service' ? (SERVICE_LABELS[item.value] || item.value)
          : field === 'campaign' && item.value ? campaignLabel(item.value)
            : item.label || item.value || (field === 'team' ? 'Unassigned' : field.startsWith('field:') ? 'Empty'
              : field === 'root_cause' ? NO_CAUSE : NOT_CLASSIFIED);
        const row = node('button', undefined, 'nq-bar');
        row.type = 'button';
        const isField = field.startsWith('field:');
        // Only the fields with a filter of their own (lists and Yes / No of the analysts or derived) drill down.
        const fieldFilter = isField && root.querySelector(`[data-nq-filter="${CSS.escape(field)}"]`);
        const blankable = ['team', 'assignee', 'root_domain', 'root_category', 'root_cause'];
        const filterValue = ((blankable.includes(field) || isField) && !item.value) ? state.unassigned : item.value;
        const chosen = filterValues(filters, field) || [];
        const active = chosen.length === 1 && chosen[0] === filterValue;
        row.classList.toggle('is-active', active);
        row.title = isField && !fieldFilter ? label : active ? `Remove the ${FIELD_LABELS[field] || historyLabel(field)} filter` : `Show only ${label}`;
        const track = node('span', undefined, 'nq-bar-track');
        const fill = node('span', undefined, 'nq-bar-fill');
        fill.style.width = `${Math.max(2, (item.count / max) * 100)}%`;
        // The colours of the PowerPoint and Word: the status, team or domain colour, else the palette in order.
        const color = (['status', 'team', 'root_domain', 'root_category', 'root_cause'].includes(field) ? optionColor(field, item.value) : '')
          || breakdown.colors?.[item.value] || PALETTE[index % PALETTE.length];
        fill.style.background = color;
        track.append(fill);
        row.append(node('span', label, 'nq-bar-label'), track, node('span', number(item.count), 'nq-bar-count'));
        row.addEventListener('click', () => {
          if (isField && !fieldFilter) return;
          if (!item.value && !blankable.includes(field) && !isField) return;
          selectOnly(field, isField ? filterValue : item.value);
        });
        card.append(row);
      });
      return card;
    }));
  };

  // -- column filters ---------------------------------------------------------------
  // Each header name with data-filter opens the values of its filter, the same selection
  // as the Filters panel.
  let columnFilter = null;
  let columnFilterAnchor = null;
  const closeColumnFilter = () => { columnFilter?.remove(); columnFilter = null; columnFilterAnchor = null; };
  // The popover follows its header button while the page or the table scrolls.
  const placeColumnFilter = () => {
    if (!columnFilter || !columnFilterAnchor) return;
    // Below the whole header row, starting at the header name.
    const rect = columnFilterAnchor.getBoundingClientRect();
    const header = (columnFilterAnchor.closest('th') || columnFilterAnchor).getBoundingClientRect();
    if (header.bottom < 0 || header.top > window.innerHeight || !columnFilterAnchor.isConnected) { closeColumnFilter(); return; }
    const width = columnFilter.offsetWidth;
    const label = columnFilterAnchor.previousElementSibling?.getBoundingClientRect() || rect;
    columnFilter.style.left = `${Math.max(8, Math.min(label.left, window.innerWidth - width - 8))}px`;
    columnFilter.style.top = `${header.bottom + 4}px`;
    columnFilter.style.maxHeight = `${Math.max(160, window.innerHeight - header.bottom - 16)}px`;
  };
  const openColumnFilter = (button, field) => {
    closeColumnFilter();
    const select = root.querySelector(`[data-nq-filter="${field}"]`);
    if (!select) return;
    const options = [...select.options];
    const popover = node('div', undefined, 'nq-column-filter');
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', `Filter by ${field.startsWith('field:') ? historyLabel(field) : (FIELD_LABELS[field] || field)}`);
    popover.dataset.field = field;
    popover.addEventListener('click', (event) => event.stopPropagation());
    const search = node('input');
    search.type = 'search';
    search.placeholder = 'Search values…';
    // Select All / None applies to the values shown by the search.
    const allLabel = node('label', undefined, 'nq-toggle nq-column-filter-all');
    const all = node('input');
    all.type = 'checkbox';
    allLabel.append(all, ' Select All / None');
    const list = node('div', undefined, 'nq-column-filter-list');
    const checkbox = (option) => {
      const label = node('label', undefined, 'nq-toggle');
      const box = node('input');
      box.type = 'checkbox';
      box.value = option.value;
      box.checked = option.selected;
      label.append(box, ` ${option.textContent}`);
      list.append(label);
      return [label, box, option];
    };
    let boxes;
    let headings = [];
    if (field === 'root_cause' || field === 'root_category') {
      // The empty value first, then the categories or causes under their domain.
      const byValue = new Map(options.map((option) => [option.value, option]));
      boxes = byValue.has(state.unassigned) ? [checkbox(byValue.get(state.unassigned))] : [];
      rootGroups(field === 'root_category' ? state.rootCauses.categories : state.rootCauses.causes).forEach(([domain, items]) => {
        const group = items.map((item) => byValue.get(item.name)).filter(Boolean);
        if (!group.length) return;
        const heading = node('p', domain || 'Other', 'nq-column-filter-group');
        heading.style.setProperty('--nq-group', domainColor(domain) || '#b8c0c6');
        list.append(heading);
        const entries = group.map(checkbox);
        headings.push([heading, entries]);
        boxes.push(...entries);
      });
    } else {
      boxes = options.map(checkbox);
    }
    if (!boxes.length) list.append(node('p', 'No values.', 'nq-muted'));
    const syncAll = () => {
      const shown = boxes.filter(([label]) => !label.hidden);
      const checked = shown.filter(([, box]) => box.checked).length;
      all.checked = shown.length > 0 && checked === shown.length;
      all.indeterminate = checked > 0 && checked < shown.length;
    };
    all.addEventListener('change', () => {
      boxes.forEach(([label, box]) => { if (!label.hidden) box.checked = all.checked; });
      syncAll();
    });
    list.addEventListener('change', syncAll);
    search.addEventListener('input', () => {
      const text = search.value.trim().toLowerCase();
      boxes.forEach(([label, , option]) => { label.hidden = Boolean(text) && !option.textContent.toLowerCase().includes(text); });
      headings.forEach(([heading, group]) => { heading.hidden = group.every(([label]) => label.hidden); });
      syncAll();
    });
    syncAll();
    const actions = node('div', undefined, 'nq-column-filter-actions');
    const apply = node('button', 'Apply', 'nq-primary-action');
    apply.type = 'button';
    apply.addEventListener('click', () => {
      boxes.forEach(([, box, option]) => { option.selected = box.checked; });
      select.dispatchEvent(new Event('multiselect:options-updated'));
      select.dispatchEvent(new Event('change', {bubbles: true}));
      closeColumnFilter();
    });
    actions.append(apply);
    popover.append(search, allLabel, list, actions);
    document.body.append(popover);
    columnFilter = popover;
    columnFilterAnchor = button;
    placeColumnFilter();
    search.focus({preventScroll: true});
  };
  window.addEventListener('scroll', () => { if (columnFilter) window.requestAnimationFrame(placeColumnFilter); }, {passive: true, capture: true});
  const renderColumnFilters = () => {
    const filters = currentFilters();
    $('nq-table').querySelectorAll('[data-filter]').forEach((label) => {
      if (!root.querySelector(`[data-nq-filter="${label.dataset.filter}"]`)) return;
      let button = label.nextElementSibling?.classList.contains('nq-column-filter-button') ? label.nextElementSibling : null;
      if (!button) {
        button = node('button', undefined, 'nq-column-filter-button');
        button.type = 'button';
        button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16l-6 7v6l-4 2v-8z"/></svg>';
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          if (columnFilter?.dataset.field === label.dataset.filter) { closeColumnFilter(); return; }
          openColumnFilter(button, label.dataset.filter);
        });
        label.after(button);
      }
      const active = Boolean(filterValues(filters, label.dataset.filter));
      button.classList.toggle('is-active', active);
      const name = label.dataset.filter.startsWith('field:') ? historyLabel(label.dataset.filter) : (FIELD_LABELS[label.dataset.filter] || label.textContent);
      button.title = active ? `${name}: filtered — change the filter` : `Filter by ${name}`;
      button.setAttribute('aria-label', button.title);
    });
  };
  document.addEventListener('click', (event) => { if (columnFilter && !columnFilter.contains(event.target)) closeColumnFilter(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && columnFilter) { event.stopPropagation(); closeColumnFilter(); } }, true);
  window.addEventListener('resize', closeColumnFilter);

  // -- table ------------------------------------------------------------------
  // Saves follow-up changes of one call and shows the call again.
  const patchCall = async (call, changes, control, message) => {
    if (control) control.disabled = true;
    try {
      const detail = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
        method: 'PATCH', body: JSON.stringify({changes, version: call.version}),
      });
      Object.assign(call, detail.call);
      if (state.detail?.call.call_key === call.call_key) renderDetail(detail);
      toast(message);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      if (control) control.disabled = false;
      loadCalls({quiet: true});
    }
  };
  const statusModeText = (call) => (call.status_mode === 'manual' ? 'Set by hand' : 'Automatic');
  const trackingSelect = (kind, call) => {
    const items = kind === 'status' ? state.options.statuses.map((item) => ({value: item.name, label: item.name, color: item.color}))
      : kind === 'team' ? [{value: '', label: 'Unassigned'}, ...state.options.teams.map((item) => ({value: item.name, label: item.name, color: item.color}))]
        : [{value: '', label: 'Unassigned'}, ...assignableUsers(call.team).map((name) => ({value: name, label: name}))];
    const current = call[kind] || '';
    if (current && !items.some((item) => item.value === current)) items.push({value: current, label: current});
    // A status set by hand can go back to the Status Rules.
    if (kind === 'status' && call.status_mode === 'manual') items.push({value: AUTO_STATUS, label: '↺ Back to automatic', action: true});
    const control = choiceControl({
      items, value: current, empty: 'Unassigned', label: `${HISTORY_LABELS[kind]} of the call`,
      title: (value) => (kind === 'status' ? `Status: ${value} (${statusModeText(call).toLowerCase()})` : `${HISTORY_LABELS[kind]}: ${value || 'Unassigned'}`),
      onChange: (value) => patchCall(call, value === AUTO_STATUS ? {status_mode: 'auto'} : {[kind]: value}, control,
        value === AUTO_STATUS ? 'The status follows the Status Rules again.' : `${HISTORY_LABELS[kind]} updated.`),
    });
    control.classList.add(`nq-pill-${kind}`);
    return control;
  };
  // Whether the status follows the Status Rules (Auto) or was chosen by hand.
  const statusModeBadge = (call) => {
    const manual = call.status_mode === 'manual';
    const badge = node('span', manual ? 'By hand' : 'Auto', `nq-status-mode${manual ? ' is-manual' : ''}`);
    badge.title = manual ? 'Chosen by hand: the Status Rules do not change it until it goes back to automatic'
      : 'Set by the Status Rules from the fields of the call';
    return badge;
  };
  const rootLabel = (category, cause) => [category, cause].filter(Boolean).join(' · ') || NOT_CLASSIFIED;
  const recommendationOf = (call) => call.rca_recommendation?.recommendation || null;
  const sourceNames = (names) => (names || []).map((name) => state.rcaSources[name] || name).join(', ');
  // Root category and cause pickers: the catalog values grouped by domain, with the values the RCA
  // sources propose first and, for a cause, the causes of the domain of the chosen category next.
  let rootPicker = null;
  const closeRootPicker = () => {
    rootPicker?.popover.remove();
    rootPicker = null;
  };
  const placeRootPicker = () => {
    if (!rootPicker) return;
    const rect = rootPicker.anchor.getBoundingClientRect();
    if (!rootPicker.anchor.isConnected || rect.bottom < 0 || rect.top > window.innerHeight) { closeRootPicker(); return; }
    const {popover} = rootPicker;
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    // Open downwards, or upwards when there is clearly more room above.
    const up = below < 260 && above > below;
    popover.style.maxHeight = `${Math.max(180, up ? above : below)}px`;
    popover.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - popover.offsetWidth - 8))}px`;
    popover.style.top = up ? `${Math.max(8, rect.top - 4 - popover.offsetHeight)}px` : `${rect.bottom + 4}px`;
  };
  // The values the RCA sources of a call propose for a root category or cause, the recommended one first.
  const proposedValues = (call, kind) => {
    const key = kind === 'root_category' ? 'category' : 'cause';
    const recommendation = recommendationOf(call);
    const names = [recommendation?.[key], ...(call.rca_recommendation?.sources || []).map((source) => source[key])].filter(Boolean);
    return [...new Set(names)];
  };
  const openRootPicker = (anchor, kind, call, choose) => {
    closeRootPicker();
    const items = kind === 'root_category' ? state.rootCauses.categories : state.rootCauses.causes;
    const current = call[kind] || '';
    const popover = node('div', undefined, 'nq-column-filter nq-cause-picker');
    popover.setAttribute('role', 'listbox');
    popover.setAttribute('aria-label', FIELD_LABELS[kind]);
    popover.addEventListener('click', (event) => event.stopPropagation());
    const search = node('input');
    search.type = 'search';
    search.placeholder = kind === 'root_category' ? 'Search root categories…' : 'Search root causes…';
    const list = node('div', undefined, 'nq-column-filter-list');
    const options = [];
    const option = (name, text, group) => {
      const button = node('button', text, 'nq-cause-option');
      button.type = 'button';
      button.setAttribute('role', 'option');
      const selected = name.toLowerCase() === current.toLowerCase();
      button.classList.toggle('is-selected', selected);
      button.classList.toggle('is-empty', !name);
      button.setAttribute('aria-selected', String(selected));
      button.addEventListener('click', () => {
        closeRootPicker();
        if (!selected) choose(name);
      });
      list.append(button);
      options.push([button, text, group]);
      return button;
    };
    const groups = [];
    const heading = (text, color, extra = '') => {
      const element = node('p', text, `nq-column-filter-group${extra}`);
      element.style.setProperty('--nq-group', color || '#b8c0c6');
      list.append(element);
      return element;
    };
    option('', kind === 'root_category' ? 'No root category' : 'No root cause', '');
    const proposed = proposedValues(call, kind).map((name) => rootItem(kind, name)).filter(Boolean);
    if (proposed.length) {
      const element = heading('Proposed by the RCA sources', '#b0234f', ' is-proposed');
      groups.push([element, proposed.map((item) => option(item.name, item.name, 'proposed'))]);
    }
    // A cause follows the domain of the chosen category; a category the domain of the chosen cause.
    const affinity = kind === 'root_cause' ? rootItem('root_category', call.root_category)?.domain
      : rootItem('root_cause', call.root_cause)?.domain;
    rootGroups(items, affinity || '').forEach(([domain, group]) => {
      const title = domain ? `${domain}${domain === affinity ? ' · same domain' : ''}` : 'Without a domain';
      const element = heading(title, domainColor(domain));
      groups.push([element, group.map((item) => option(item.name, item.name, domain))]);
    });
    search.addEventListener('input', () => {
      const text = search.value.trim().toLowerCase();
      options.forEach(([button, label, group]) => {
        button.hidden = Boolean(text) && !`${group} ${label}`.toLowerCase().includes(text);
      });
      groups.forEach(([element, buttons]) => { element.hidden = buttons.every((button) => button.hidden); });
    });
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        list.querySelector('.nq-cause-option:not([hidden]):not(.is-empty)')?.click();
      }
    });
    popover.append(search, list);
    document.body.append(popover);
    rootPicker = {popover, anchor};
    placeRootPicker();
    // Show the current value; only the list scrolls (scrollIntoView would also scroll the page).
    const selected = list.querySelector('.is-selected');
    if (selected) list.scrollTop = selected.offsetTop - list.clientHeight / 2;
    search.focus({preventScroll: true});
  };
  document.addEventListener('click', (event) => { if (rootPicker && !rootPicker.popover.contains(event.target)) closeRootPicker(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && rootPicker) { event.stopPropagation(); rootPicker.anchor.focus(); closeRootPicker(); }
  }, true);
  window.addEventListener('scroll', (event) => {
    if (rootPicker && !rootPicker.popover.contains(event.target)) window.requestAnimationFrame(placeRootPicker);
  }, {passive: true, capture: true});
  window.addEventListener('resize', closeRootPicker);
  // A modern dropdown: the value as a pill in its colour, and every choice in its colour in a popover (with a search
  // for long lists). Items are {value, label, color, action}; an action (Back to automatic) is not a value.
  const openChoicePicker = (anchor, items, current, choose, label) => {
    closeRootPicker();
    const popover = node('div', undefined, 'nq-column-filter nq-cause-picker nq-choice-picker');
    popover.setAttribute('role', 'listbox');
    popover.setAttribute('aria-label', label);
    popover.addEventListener('click', (event) => event.stopPropagation());
    const list = node('div', undefined, 'nq-column-filter-list');
    const options = items.map((item) => {
      const option = node('button', undefined, `nq-choice-option${item.action ? ' is-action' : ''}`);
      option.type = 'button';
      option.setAttribute('role', 'option');
      const selected = !item.action && item.value === current;
      option.classList.toggle('is-selected', selected);
      option.setAttribute('aria-selected', String(selected));
      const chip = node('span', item.label, 'nq-pill');
      if (item.color) paintPill(chip, item.color);
      else if (!item.value || item.action) chip.classList.add('is-empty');
      option.append(chip);
      option.addEventListener('click', () => {
        closeRootPicker();
        if (!selected) choose(item);
      });
      list.append(option);
      return [option, item.label];
    });
    let search = null;
    if (items.length > 10) {
      search = node('input');
      search.type = 'search';
      search.placeholder = 'Search…';
      search.addEventListener('input', () => {
        const query = search.value.trim().toLowerCase();
        options.forEach(([option, text]) => { option.hidden = Boolean(query) && !text.toLowerCase().includes(query); });
      });
      search.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          list.querySelector('.nq-choice-option:not([hidden])')?.click();
        }
      });
      popover.append(search);
    }
    popover.append(list);
    document.body.append(popover);
    rootPicker = {popover, anchor};
    placeRootPicker();
    const selected = list.querySelector('.is-selected');
    if (selected) list.scrollTop = selected.offsetTop - list.clientHeight / 2;
    (search || selected || list.querySelector('.nq-choice-option'))?.focus({preventScroll: true});
  };
  // The arrows move between the choices of an open picker.
  document.addEventListener('keydown', (event) => {
    if (!rootPicker || !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    const options = [...rootPicker.popover.querySelectorAll('.nq-choice-option:not([hidden]), .nq-cause-option:not([hidden])')];
    if (!options.length) return;
    event.preventDefault();
    const index = options.indexOf(document.activeElement);
    const next = event.key === 'ArrowDown' ? Math.min(options.length - 1, index + 1) : Math.max(0, index - 1);
    options[next].focus();
  });
  const choiceControl = ({items, value, empty = '—', label, onChange, title = null}) => {
    const button = node('button', undefined, 'nq-pill-select nq-cause-picker-button nq-choice');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-label', label);
    let current = value || '';
    const paint = () => {
      const item = items.find((entry) => !entry.action && entry.value === current);
      button.textContent = item ? item.label : (current || empty);
      paintPill(button, item?.color || '');
      button.classList.toggle('is-empty', !current);
      button.title = title ? title(current) : `${label}: ${current || empty}`;
    };
    paint();
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (rootPicker?.anchor === button) { closeRootPicker(); return; }
      openChoicePicker(button, items, current, (item) => {
        if (!item.action) {
          current = item.value;
          paint();
        }
        onChange(item.value, item);
      }, label);
    });
    button.setValue = (chosen) => { current = chosen || ''; paint(); };
    return button;
  };
  // Yes and No in their colours.
  const YES_NO_COLORS = {Yes: '#245a96', No: '#9aa5ad'};
  const fieldChoices = (field, value = '') => {
    const names = field.type === 'yes_no' ? ['Yes', 'No'] : field.options.map((option) => option.name);
    if (value && !names.includes(value)) names.push(value);
    return [{value: '', label: '—'}, ...names.map((name) => ({value: name, label: name,
      color: field.type === 'yes_no' ? YES_NO_COLORS[name] : optionColorOf(field, name)}))];
  };
  // A picker button for the root category (filled with its domain colour) or cause (outlined).
  const rootPickerButton = (kind, call) => {
    const value = call[kind] || '';
    const empty = kind === 'root_category' ? 'Root category…' : 'Root cause…';
    const button = node('button', value || empty, 'nq-pill-select nq-root-select nq-cause-picker-button');
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-label', `${FIELD_LABELS[kind]} of the call`);
    if (kind === 'root_category') paintPill(button, optionColor(kind, value));
    else outlinePill(button, optionColor(kind, value));
    button.classList.toggle('is-empty', !value);
    const domain = rootItem(kind, value)?.domain;
    button.title = `${FIELD_LABELS[kind]}: ${value || 'none'}${domain ? ` (${domain})` : ''}`;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      if (rootPicker?.anchor === button) { closeRootPicker(); return; }
      openRootPicker(button, kind, call, (name) => patchCall(call, {[kind]: name}, button, `${FIELD_LABELS[kind]} updated.`));
    });
    return button;
  };
  // The recommended root category and cause of a call without them, to accept with one click.
  const recommendationChip = (call) => {
    const recommendation = recommendationOf(call);
    if (!recommendation || call.root_category || call.root_cause) return null;
    const text = rootLabel(recommendation.category, recommendation.cause);
    const title = `Recommended: ${text}${recommendation.domain ? ` (${recommendation.domain})` : ''}\n`
      + `${CONFIDENCE_LABELS[recommendation.confidence] || ''} · ${sourceNames(recommendation.sources)}`;
    const chip = node(state.user.can_edit ? 'button' : 'span', undefined, `nq-root-suggestion is-${recommendation.confidence}`);
    chip.append(node('span', '', 'nq-confidence-dot'), node('span', text));
    chip.title = state.user.can_edit ? `${title}\nClick to accept it` : title;
    if (state.user.can_edit) {
      chip.type = 'button';
      chip.addEventListener('click', (event) => {
        event.stopPropagation();
        patchCall(call, {root_category: recommendation.category, root_cause: recommendation.cause}, chip, 'Recommendation accepted.');
      });
    }
    return chip;
  };
  // The root cause of a call: its root category above and its root cause below, each in the colour of its
  // domain, and the recommended ones while it has none.
  const rootCauseControl = (call) => {
    const wrapper = node('div', undefined, 'nq-root-cell');
    if (state.user.can_edit) wrapper.append(rootPickerButton('root_category', call), rootPickerButton('root_cause', call));
    else {
      wrapper.append(pill('root_category', call.root_category, NOT_CLASSIFIED));
      if (call.root_cause) wrapper.append(pill('root_cause', call.root_cause, NO_CAUSE));
    }
    const chip = recommendationChip(call);
    if (chip) wrapper.append(chip);
    return wrapper;
  };
  // A team with members is assigned to its members only.
  const assignableUsers = (team) => {
    const members = state.options.teams.find((item) => item.name === team)?.members || [];
    return members.length ? members : state.users;
  };
  // -- optional columns: built-in call columns, CDR columns and analysis fields ---------------
  const optionalColumns = () => [
    ...state.tableColumns.builtin.map((key) => ({key, label: state.optionalColumns[key] || key, sort: key})),
    ...state.tableColumns.cdr.map((name) => ({key: `cdr:${name}`, label: name, sort: `cdr:${name}`})),
  ];
  // The catalog fields shown as columns; the follow-up ones (status, team, root cause…) have fixed columns.
  const fieldColumns = () => state.fields.filter((field) => field.in_table && field.source !== 'tracking');
  // The filter of each optional column: CDR uses the CDRs filter, the others filter by their own values.
  const OWN_COLUMN_FILTERS = {cdr: 'datasets'};
  const columnFilterKey = (column) => OWN_COLUMN_FILTERS[column.key] || `column:${column.key}`;
  const columnFilters = () => optionalColumns().filter((column) => !OWN_COLUMN_FILTERS[column.key])
    .map((column) => ({label: column.label, filter: columnFilterKey(column)}));
  const optionColorOf = (field, value) => field.options?.find((option) => option.name === value)?.color || '';
  const bindSort = (header) => {
    if (header.dataset.sortBound) return;
    header.dataset.sortBound = '1';
    header.tabIndex = 0;
    const sort = () => {
      if (state.sort === header.dataset.sort) state.direction = state.direction === 'asc' ? 'desc' : 'asc';
      else { state.sort = header.dataset.sort; state.direction = header.dataset.sort === 'start_time' ? 'desc' : 'asc'; }
      state.page = 1;
      loadCalls();
    };
    header.addEventListener('click', sort);
    header.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); } });
  };
  const headerCell = (label, sortKey, filterKey = '', section = null) => {
    const cell = node('th', undefined, 'nq-sort-pair nq-dynamic-col');
    const item = node('span', undefined, 'nq-header-item');
    const name = node('span', label);
    name.dataset.sort = sortKey;
    if (filterKey) name.dataset.filter = filterKey;
    item.append(name);
    cell.append(item);
    // A catalog field shows the colour of its section above its name.
    if (section) {
      cell.classList.add('nq-section-col');
      cell.style.setProperty('--nq-section', section.color);
      cell.title = `${section.label} · ${label}`;
    }
    bindSort(name);
    return cell;
  };
  // -- column order: a header dragged onto another moves its column; each browser remembers it per workspace --
  const STATIC_HEADERS = [...($('nq-table')?.tHead.rows[0].cells || [])];
  const COLUMN_ORDER_STORAGE = `nq-column-order:${$('nq-table')?.dataset.workspace || ''}`;
  // Optional columns shown by default before a fixed column instead of after Result / Failure.
  const DEFAULT_COLUMN_PLACES = {session_type: 'test_name'};
  // The column keys in the order the rows are built, and in the order they are shown.
  let naturalColumns = [];
  let shownColumns = [];
  let draggedColumn = '';
  const columnKeyOf = (cell) => cell.querySelector('[data-sort]')?.dataset.sort || '';
  const storedColumnOrder = () => {
    try {
      const order = JSON.parse(localStorage.getItem(COLUMN_ORDER_STORAGE) || '[]');
      return Array.isArray(order) ? order.map(String) : [];
    } catch (_error) {
      return [];
    }
  };
  const defaultColumnOrder = () => {
    const order = [...naturalColumns];
    Object.entries(DEFAULT_COLUMN_PLACES).forEach(([key, before]) => {
      if (!order.includes(key) || !order.includes(before)) return;
      order.splice(order.indexOf(key), 1);
      order.splice(order.indexOf(before), 0, key);
    });
    return order;
  };
  const saveColumnOrder = (order) => {
    try {
      if (order.join('|') === defaultColumnOrder().join('|')) localStorage.removeItem(COLUMN_ORDER_STORAGE);
      else localStorage.setItem(COLUMN_ORDER_STORAGE, JSON.stringify(order));
    } catch (_error) {
      // Without browser storage the order lasts until the page is reloaded.
    }
  };
  const clearDropMarks = () => $('nq-table').tHead.querySelectorAll('.is-drop-before, .is-drop-after')
    .forEach((cell) => cell.classList.remove('is-drop-before', 'is-drop-after'));
  const moveColumn = (key, target, after) => {
    const order = shownColumns.filter((item) => item !== key);
    order.splice(order.indexOf(target) + (after ? 1 : 0), 0, key);
    saveColumnOrder(order);
    applyColumnOrder(order);
    if (state.result) renderRows(state.result);
  };
  const bindColumnDrag = (cell) => {
    if (cell.dataset.dragBound) return;
    cell.dataset.dragBound = '1';
    cell.draggable = true;
    cell.addEventListener('dragstart', (event) => {
      draggedColumn = columnKeyOf(cell);
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', draggedColumn);
      cell.classList.add('is-dragging');
    });
    cell.addEventListener('dragend', () => {
      draggedColumn = '';
      cell.classList.remove('is-dragging');
      clearDropMarks();
    });
    cell.addEventListener('dragover', (event) => {
      if (!draggedColumn || draggedColumn === columnKeyOf(cell)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      const box = cell.getBoundingClientRect();
      const after = event.clientX > box.left + box.width / 2;
      clearDropMarks();
      cell.classList.add(after ? 'is-drop-after' : 'is-drop-before');
    });
    cell.addEventListener('dragleave', (event) => {
      if (!cell.contains(event.relatedTarget)) cell.classList.remove('is-drop-before', 'is-drop-after');
    });
    cell.addEventListener('drop', (event) => {
      event.preventDefault();
      const target = columnKeyOf(cell);
      const after = cell.classList.contains('is-drop-after');
      clearDropMarks();
      if (draggedColumn && draggedColumn !== target) moveColumn(draggedColumn, target, after);
    });
  };
  // Shows the header in the stored order; columns missing from it (newly added) keep their default place.
  const applyColumnOrder = (stored = storedColumnOrder()) => {
    const row = $('nq-table').tHead.rows[0];
    const movable = [...row.cells].filter((cell) => columnKeyOf(cell));
    const defaults = defaultColumnOrder();
    const order = stored.filter((key) => naturalColumns.includes(key));
    defaults.forEach((key, index) => {
      if (order.includes(key)) return;
      const previous = defaults.slice(0, index).reverse().find((item) => order.includes(item));
      order.splice(previous ? order.indexOf(previous) + 1 : 0, 0, key);
    });
    shownColumns = order;
    const byKey = new Map(movable.map((cell) => [columnKeyOf(cell), cell]));
    row.append(...order.map((key) => byKey.get(key)));
    movable.forEach(bindColumnDrag);
    $('nq-column-order-reset').hidden = order.join('|') === defaults.join('|');
  };
  // The cells of a row, built in the natural order, are shown in the order of the header.
  const orderRowCells = (row) => {
    if (!shownColumns.length) return;
    const cells = [...row.cells].slice(row.cells.length - naturalColumns.length);
    if (cells.length !== naturalColumns.length) return;
    row.append(...shownColumns.map((key) => cells[naturalColumns.indexOf(key)]));
  };
  // The optional columns follow Result / Failure, the analysis fields follow the root cause; then the column order applies.
  const renderDynamicHeaders = () => {
    const row = $('nq-table').tHead.rows[0];
    row.querySelectorAll('.nq-dynamic-col').forEach((cell) => cell.remove());
    // The fixed columns go back to the order of the page before the others are placed.
    row.append(...STATIC_HEADERS);
    const after = (sortKey) => row.querySelector(`[data-sort="${sortKey}"]`)?.closest('th');
    let anchor = after('result');
    optionalColumns().forEach((column) => {
      const cell = headerCell(column.label, column.sort, columnFilterKey(column));
      anchor.after(cell);
      anchor = cell;
    });
    // The RCA fields come before the root category and cause they lead to, the other fields after them.
    const rootHeader = after('root_category');
    rootHeader.classList.add('nq-section-col');
    rootHeader.style.setProperty('--nq-section', sectionOf('rca').color);
    const filterable = new Set(filterableFields().map((field) => field.key));
    anchor = rootHeader;
    fieldColumns().forEach((field) => {
      const cell = headerCell(field.label, `field:${field.key}`, filterable.has(field.key) ? `field:${field.key}` : '', sectionOf(field.section));
      if (field.section === 'rca') rootHeader.before(cell);
      else { anchor.after(cell); anchor = cell; }
    });
    naturalColumns = [...row.cells].map(columnKeyOf).filter(Boolean);
    applyColumnOrder();
  };
  const saveFieldValue = (call, key, value, control) => patchCall(call, {fields: {[key]: value}}, control,
    `${historyLabel(`field:${key}`)} updated.`);
  // A list or Yes / No field of the analysts is chosen in the row; the other fields are shown here and
  // edited in the call; fields from the CDR, the RCA script or derived are read only.
  const fieldCell = (call, field) => {
    const cell = node('td', undefined, 'nq-tracking-cell nq-field-cell');
    const value = String((field.source === 'user' ? call.fields?.[field.key] : call.values?.[field.key]) ?? '');
    if (['list', 'yes_no'].includes(field.type) && field.source === 'user' && state.user.can_edit) {
      const picker = choiceControl({items: fieldChoices(field, value), value, label: `${field.label} of the call`,
        onChange: (chosen) => saveFieldValue(call, field.key, chosen, picker)});
      picker.classList.add('nq-field-select');
      cell.append(picker);
      return cell;
    }
    if (['list', 'yes_no'].includes(field.type) && value) {
      const element = node('span', value, 'nq-pill');
      paintPill(element, field.type === 'yes_no' ? YES_NO_COLORS[value] || '' : optionColorOf(field, value));
      cell.append(element);
    } else {
      const text = node('span', field.type === 'date' ? value : value || '—', value ? 'nq-field-text' : 'nq-muted');
      if (value) text.title = value;
      cell.append(text);
    }
    return cell;
  };
  const optionalCell = (call, column) => {
    let value;
    if (column.key.startsWith('cdr:')) value = call.extra?.[column.key.slice(4)] || '';
    else if (column.key === 'end_time') value = call.end_time ? cdrTime(call.end_time) : '';
    else if (column.key === 'cdr') value = call.dataset_name || '';
    else value = call[column.key] ?? '';
    const cell = node('td', String(value || '—'), `nq-optional-cell${value ? '' : ' nq-muted'}`);
    if (value) cell.title = `${column.label}: ${value}`;
    return cell;
  };
  const versionBadge = (call) => {
    if (!call.version_state) return null;
    const label = state.versionLabels[call.version_state] || call.version_state;
    const badge = node('span', label, `nq-version is-${call.version_state.replace(/_/g, '-')}`);
    const latest = call.latest_dataset_name && call.latest_dataset_name !== call.dataset_name ? `\nLatest CDR: ${call.latest_dataset_name}` : '';
    badge.title = `${VERSION_HINTS[call.version_state] || label}.\nShown from: ${call.dataset_name || '—'}${latest}`;
    return badge;
  };

  const renderRows = (result) => {
    const body = $('nq-rows');
    const columns = $('nq-table').tHead.rows[0].cells.length;
    if (!result.calls.length) {
      const cell = node('td', result.total === 0 && !Object.keys(currentFilters()).length
        ? 'No Non-Qualified Calls in the ready CDRs of this workspace.' : 'No calls match the filters.', 'nq-empty');
      cell.colSpan = columns;
      const row = node('tr');
      row.append(cell);
      body.replaceChildren(row);
      return;
    }
    // Each cell knows the name of its column: on phones the rows are cards that show it above the value.
    const labels = [...$('nq-table').tHead.rows[0].cells].map((cell) => [...cell.querySelectorAll('[data-sort]')]
      .map((item) => item.textContent.trim()).filter(Boolean).join(' · '));
    body.replaceChildren(...result.calls.map((call) => {
      const row = node('tr');
      row.dataset.callKey = call.call_key;
      row.classList.toggle('is-selected', state.selected.has(call.call_key));
      if (state.user.can_edit) {
        const box = node('input');
        box.type = 'checkbox';
        box.checked = state.selected.has(call.call_key);
        box.setAttribute('aria-label', 'Select this call');
        box.addEventListener('click', (event) => event.stopPropagation());
        box.addEventListener('change', () => {
          if (box.checked) state.selected.add(call.call_key); else state.selected.delete(call.call_key);
          row.classList.toggle('is-selected', box.checked);
          renderBulk();
        });
        const cell = node('td', undefined, 'nq-select-cell');
        cell.append(box);
        row.append(cell);
      }
      // Start time with the service below it.
      const start = node('td', undefined, 'nq-start-cell');
      // The minute is enough in the row; the whole time shows on hover.
      const startTime = node('span', cdrTime(call.start_time).replace(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}):\d{2}$/, '$1'), 'nq-nowrap');
      startTime.title = cdrTime(call.start_time);
      start.append(startTime, node('span', call.service_label, `nq-service nq-service-${call.service}`));
      if (call.service === 'speech' && Number(call.nq_samples) > 1) {
        const samples = node('span', `${number(call.nq_samples)} NQ samples`, 'nq-samples-badge');
        samples.title = 'Non-Qualified samples of this Speech call: open the call to follow each one up';
        start.append(samples);
      }
      // The result pill before the failure classification and category.
      const failure = node('td', undefined, 'nq-failure');
      failure.append(node('span', call.result || '—', `nq-result ${resultClass(call.result)}`));
      if (call.failure_classification || call.failure_category) {
        failure.append(node('strong', call.failure_classification || call.failure_category));
        if (call.failure_classification && call.failure_category) failure.append(node('span', call.failure_category));
        failure.title = [call.failure_subcategory, call.failure_comment].filter(Boolean).join('\n');
      } else {
        failure.append(node('span', 'Not classified', 'nq-muted'));
      }
      const badge = versionBadge(call);
      if (badge) failure.append(badge);
      const tracking = (...kinds) => {
        const cell = node('td', undefined, `nq-tracking-cell${kinds.length > 1 ? ' nq-tracking-stack' : ''}`);
        kinds.forEach((kind) => cell.append(state.user.can_edit ? trackingSelect(kind, call) : pill(kind, call[kind])));
        return cell;
      };
      // The status with the time (and author) of the last change of the call's follow-up.
      const status = tracking('status');
      status.classList.add('nq-tracking-stack');
      const updated = node('span', undefined, 'nq-status-updated');
      updated.append(statusModeBadge(call), ` ${call.updated_at ? `Updated ${relativeTime(call.updated_at)}${call.updated_by ? ` by ${call.updated_by}` : ''}` : 'Not followed up yet'}`);
      updated.title = call.updated_at ? `Last follow-up by ${call.updated_by || '—'} · ${exactTime(call.updated_at)}` : 'Nobody has changed this call yet';
      status.append(updated);
      const comments = node('td', undefined, 'nq-comments-cell');
      const commentButton = node('button', undefined, 'nq-comment-button');
      commentButton.type = 'button';
      const bubble = node('span', String(call.comment_count || 0), `nq-comment-count${call.comment_count ? '' : ' is-empty'}`);
      commentButton.append(bubble);
      if (call.last_comment) {
        const preview = node('span', undefined, 'nq-comment-preview');
        preview.append(node('strong', call.last_comment.created_by), node('span', call.last_comment.body));
        commentButton.append(preview);
        commentButton.title = `${call.last_comment.created_by} · ${exactTime(call.last_comment.created_at)}\n${call.last_comment.body}`;
      } else {
        commentButton.append(node('span', state.user.can_edit ? 'Add a comment' : 'No comments', 'nq-comment-preview nq-muted'));
      }
      commentButton.addEventListener('click', (event) => {
        event.stopPropagation();
        openDetail(call.call_key, {focusComposer: true});
      });
      const openButton = node('button', '›', 'nq-open-button');
      openButton.type = 'button';
      openButton.setAttribute('aria-label', 'Open the call details and activity');
      const commentActions = node('div', undefined, 'nq-comment-actions-cell');
      commentActions.append(commentButton, openButton);
      comments.append(commentActions);
      // Two related values share a cell: the main one first, the other below it.
      const stacked = (main, secondary) => {
        const cell = node('td', undefined, 'nq-stacked');
        cell.append(node('strong', main || '—'));
        if (secondary) cell.append(node('span', secondary));
        cell.title = [main, secondary].filter(Boolean).join(' · ');
        return cell;
      };
      const root = node('td', undefined, 'nq-tracking-cell');
      root.append(rootCauseControl(call));
      row.append(
        start, stacked(call.operator, call.vendor), stacked(call.region, call.cluster), stacked(call.city, campaignLabel(call.campaign)),
        stacked(call.test_name, call.technology), failure, ...optionalColumns().map((column) => optionalCell(call, column)),
        tracking('team', 'assignee'), ...fieldColumns().filter((field) => field.section === 'rca').map((field) => fieldCell(call, field)),
        root, ...fieldColumns().filter((field) => field.section !== 'rca').map((field) => fieldCell(call, field)), status, comments,
      );
      orderRowCells(row);
      [...row.cells].forEach((cell, index) => { if (labels[index]) cell.dataset.label = labels[index]; });
      row.addEventListener('click', (event) => {
        if (event.target.closest('select, input, a')) return;
        openDetail(call.call_key);
      });
      return row;
    }));
  };
  const renderSortHeaders = () => {
    $('nq-table').querySelectorAll('[data-sort]').forEach((header) => {
      const active = header.dataset.sort === state.sort;
      header.classList.toggle('is-sorted', active);
      header.dataset.direction = active ? state.direction : '';
      header.setAttribute('aria-sort', active ? (state.direction === 'asc' ? 'ascending' : 'descending') : 'none');
    });
  };
  const renderPagination = (result) => {
    const host = $('nq-pagination');
    if (result.pages <= 1) { host.replaceChildren(); return; }
    const button = (label, page, disabled = false, current = false) => {
      const element = node('button', label, current ? 'is-current nq-page-number' : 'nq-page-number');
      element.type = 'button';
      element.disabled = disabled;
      if (current) element.setAttribute('aria-current', 'page');
      element.addEventListener('click', () => { state.page = page; loadCalls(); });
      return element;
    };
    // First, previous, next and last are arrows, as in every pager of the application.
    const arrow = (name, path, page, disabled) => {
      const element = button('', page, disabled);
      element.className = '';
      element.setAttribute('aria-label', `${name} page`);
      element.title = `${name} page`;
      element.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
      return element;
    };
    const pages = new Set([1, result.pages, result.page - 1, result.page, result.page + 1]);
    const items = [arrow('First', 'M5 5v14M18 6l-6 6 6 6M12 6l-6 6 6 6', 1, result.page <= 1),
      arrow('Previous', 'M15 6l-6 6 6 6', result.page - 1, result.page <= 1)];
    let previous = 0;
    [...pages].filter((page) => page >= 1 && page <= result.pages).sort((a, b) => a - b).forEach((page) => {
      if (page - previous > 1) items.push(node('span', '…', 'nq-ellipsis'));
      items.push(button(String(page), page, false, page === result.page));
      previous = page;
    });
    // On phones the page among the pages takes the place of the page numbers.
    items.push(node('span', `Page ${number(result.page)} of ${number(result.pages)}`, 'nq-page-status'),
      arrow('Next', 'M9 6l6 6-6 6', result.page + 1, result.page >= result.pages),
      arrow('Last', 'M19 5v14M6 6l6 6-6 6M12 6l6 6-6 6', result.pages, result.page >= result.pages));
    host.replaceChildren(...items);
  };
  // The actions of the selected calls cover the toolbar right above the table, so the table
  // does not move, and stay at the top of the window while the table is scrolled.
  const placeBulk = () => {
    const bulk = $('nq-bulk');
    if (!bulk || bulk.hidden) return;
    const toolbar = root.querySelector('.nq-toolbar');
    const table = $('nq-table').closest('.nq-table-wrap').getBoundingClientRect();
    const anchor = toolbar.getBoundingClientRect();
    const top = Math.min(Math.max(12, anchor.top), Math.max(12, table.bottom - bulk.offsetHeight));
    bulk.style.top = `${top}px`;
    bulk.style.left = `${table.left}px`;
    bulk.style.width = `${table.width}px`;
    bulk.classList.toggle('is-floating', anchor.top < 12);
  };
  let placeFrame = 0;
  const schedulePlaceBulk = () => {
    if (placeFrame) return;
    placeFrame = window.requestAnimationFrame(() => { placeFrame = 0; placeBulk(); });
  };
  window.addEventListener('scroll', schedulePlaceBulk, {passive: true});
  window.addEventListener('resize', schedulePlaceBulk);
  const renderBulk = () => {
    const bulk = $('nq-bulk');
    if (!bulk) return;
    // The actions of the selected calls go with the table.
    bulk.hidden = !state.selected.size || Boolean(panelOf('calls')?.hidden);
    placeBulk();
    $('nq-bulk-count').textContent = `${number(state.selected.size)} selected`;
    const pageBox = $('nq-select-page');
    if (pageBox && state.result) {
      const keys = state.result.calls.map((call) => call.call_key);
      const chosen = keys.filter((key) => state.selected.has(key)).length;
      pageBox.checked = keys.length > 0 && chosen === keys.length;
      pageBox.indeterminate = chosen > 0 && chosen < keys.length;
    }
  };
  const fillBulkSelects = () => {
    const fill = (id, placeholder, entries) => {
      const select = $(id);
      if (!select) return;
      select.replaceChildren(node('option', placeholder), ...entries.map(([value, label]) => {
        const option = node('option', label);
        option.value = value;
        return option;
      }));
      select.options[0].value = '';
    };
    fill('nq-bulk-status', 'Set status…', [...state.options.statuses.map((item) => [item.name, item.name]),
      [AUTO_STATUS, '↺ Back to automatic']]);
    fill('nq-bulk-team', 'Set team…', [[state.unassigned, 'Unassigned'], ...state.options.teams.map((item) => [item.name, item.name])]);
    fill('nq-bulk-assignee', 'Assign to…', [[state.unassigned, 'Unassigned'], ...state.users.map((name) => [name, name])]);
    // Root categories and causes under their domain.
    [['nq-bulk-category', 'Set root category…', NOT_CLASSIFIED, state.rootCauses.categories],
      ['nq-bulk-root', 'Set root cause…', NO_CAUSE, state.rootCauses.causes]].forEach(([id, placeholder, empty, items]) => {
      const select = $(id);
      if (!select) return;
      select.replaceChildren(node('option', placeholder), node('option', empty));
      select.options[0].value = '';
      select.options[1].value = state.unassigned;
      rootGroups(items).forEach(([domain, group]) => {
        const optgroup = node('optgroup');
        optgroup.label = domain || 'Without a domain';
        optgroup.append(...group.map((item) => {
          const option = node('option', item.name);
          option.value = item.name;
          return option;
        }));
        select.append(optgroup);
      });
    });
    const fieldSelect = $('nq-bulk-field');
    if (fieldSelect) {
      const choosable = state.fields.filter((field) => ['list', 'yes_no'].includes(field.type) && field.source === 'user');
      fieldSelect.hidden = !choosable.length;
      fieldSelect.replaceChildren(node('option', 'Set field…'));
      fieldSelect.options[0].value = '';
      choosable.forEach((field) => {
        const group = node('optgroup');
        group.label = field.label;
        const values = field.type === 'yes_no' ? ['Yes', 'No'] : field.options.map((option) => option.name);
        group.append(...[...values, ''].map((value) => {
          const option = node('option', value || `${field.label}: empty`);
          option.value = `${field.key}${ROOT_SEPARATOR}${value}`;
          return option;
        }));
        fieldSelect.append(group);
      });
    }
  };

  // -- views and panels on screen ---------------------------------------------------------
  // The panels calculated on their own after each change of the calls (the Summary comes with the calls).
  const PANEL_LOADERS = {rates: loadRates, progress: loadProgress, lifecycle: loadLifecycle, root: loadRootCauses, sources: loadSources};
  const panelOf = (name) => root.querySelector(`[data-nq-loader="${name}"]`);
  const panelShown = (name) => {
    const panel = panelOf(name);
    return Boolean(panel && !panel.hidden && panel.open);
  };
  // The panels left out of the last filter change, calculated once they are shown.
  const refreshStale = () => {
    if (state.stale.has('summary') && panelShown('summary')) { loadCalls({quiet: true}); return; }
    Object.entries(PANEL_LOADERS).forEach(([name, load]) => {
      if (state.stale.has(name) && panelShown(name)) {
        state.stale.delete(name);
        void load();
      }
    });
  };
  const VIEW_STORAGE = `nq-view:${$('nq-table').dataset.workspace || ''}`;
  const VIEWS = ['calls', 'dashboards', 'all'];
  const applyView = (view) => {
    state.view = VIEWS.includes(view) ? view : 'calls';
    root.querySelectorAll('[data-nq-view-panel]').forEach((panel) => {
      panel.hidden = state.view !== 'all' && panel.dataset.nqViewPanel !== state.view;
    });
    $('nq-view-switch').querySelectorAll('[data-nq-view]').forEach((button) => {
      const active = button.dataset.nqView === state.view;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
    });
    try {
      localStorage.setItem(VIEW_STORAGE, state.view);
    } catch (_error) {
      // Without browser storage the view lasts until the page is reloaded.
    }
    renderBulk();
  };
  $('nq-view-switch').querySelectorAll('[data-nq-view]').forEach((button) => button.addEventListener('click', () => {
    applyView(button.dataset.nqView);
    refreshStale();
  }));
  root.querySelectorAll('[data-nq-loader]').forEach((panel) => panel.addEventListener('toggle', () => { if (panel.open) refreshStale(); }));
  applyView((() => {
    try {
      return localStorage.getItem(VIEW_STORAGE) || 'calls';
    } catch (_error) {
      return 'calls';
    }
  })());

  // -- loading ----------------------------------------------------------------
  // The indexing runs in the background (when the server is idle, the first time, or on Reindex): the badge says
  // so, and the page follows it with a light status request, then reloads its calls.
  let indexWatch = null;
  const watchIndexing = () => {
    if (indexWatch) return;
    indexWatch = window.setTimeout(async function check() {
      try {
        const {sync} = await api('/api/non-qualified-calls/index-status');
        if (sync.indexing) {
          renderSync(sync, {watch: false});
          indexWatch = window.setTimeout(check, 4000);
          return;
        }
        indexWatch = null;
        await loadState();
      } catch (_error) {
        indexWatch = window.setTimeout(check, 8000);
      }
    }, 4000);
  };
  const renderSync = (sync, {watch = true} = {}) => {
    if (!sync) return;
    const when = sync.synced_at ? ` · indexed ${relativeTime(sync.synced_at)}` : '';
    const pending = sync.indexing ? (sync.reindexing ? ' · reindexing every CDR…' : ' · indexing…')
      : sync.pending ? ` · ${number(sync.pending)} CDR${sync.pending === 1 ? '' : 's'} waiting to be indexed` : '';
    $('nq-sync').textContent = `${number(sync.calls)} Non-Qualified Calls in ${number(sync.datasets)} CDRs${when}${pending}`;
    $('nq-sync').title = [sync.synced_at ? `CDRs last indexed ${exactTime(sync.synced_at)}` : '',
      sync.pending && !sync.indexing ? 'New or changed CDRs are indexed once the server is idle, or now with Reindex' : '',
      sync.error ? `The last indexing failed: ${sync.error}` : ''].filter(Boolean).join('\n');
    $('nq-refresh').disabled = Boolean(sync.indexing);
    if (sync.indexing && watch) watchIndexing();
  };
  async function loadCalls({quiet = false} = {}) {
    const token = ++state.requestToken;
    const filters = currentFilters();
    if (state.filtersRestored) saveFilters(filters);
    if (!quiet) {
      $('nq-count').textContent = 'Loading calls…';
      root.classList.add('is-loading');
    }
    try {
      // The breakdowns of the Summary are only asked for while it is shown.
      const breakdowns = panelShown('summary');
      const result = await api('/api/non-qualified-calls/calls', {
        method: 'POST',
        body: JSON.stringify({filters, sort: state.sort, direction: state.direction, page: state.page, page_size: state.pageSize, breakdowns}),
        // A quiet reload is the page keeping itself current, not someone using the application.
        ...(quiet ? {headers: {'X-Background-Refresh': '1'}} : {}),
      });
      if (token !== state.requestToken) return;
      state.result = result;
      state.page = result.page;
      renderSync(result.sync);
      renderActiveFilters(filters);
      renderColumnFilters();
      if (breakdowns) {
        renderSummary(result);
        state.stale.delete('summary');
      } else {
        state.stale.add('summary');
      }
      renderRows(result);
      renderSortHeaders();
      renderPagination(result);
      renderBulk();
      $('nq-view-count').textContent = number(result.total);
      // Only the panels on screen (shown and unfolded) are calculated; the others when they are opened.
      Object.entries(PANEL_LOADERS).forEach(([name, load]) => {
        if (panelShown(name)) {
          state.stale.delete(name);
          void load();
        } else {
          state.stale.add(name);
        }
      });
      const first = result.total ? (result.page - 1) * result.page_size + 1 : 0;
      const last = Math.min(result.total, result.page * result.page_size);
      $('nq-count').textContent = result.total ? `Showing ${number(first)}–${number(last)} of ${number(result.total)} calls` : 'No calls';
    } catch (error) {
      if (token !== state.requestToken) return;
      $('nq-count').textContent = error.message;
      if (!quiet) toast(error.message, 'error');
    } finally {
      if (token === state.requestToken) root.classList.remove('is-loading');
    }
  }
  const scheduleLoad = debounce(() => { state.page = 1; loadCalls(); }, 300);

  // -- progress view --------------------------------------------------------------
  const PALETTE = ['#b0234f', '#0f6f7d', '#e08a1e', '#6a63c9', '#2e8b57', '#245a96', '#b85b20', '#7b8790', '#5b6b2e', '#c8365f'];
  const GRANULARITY_LABELS = {week: 'Week', month: 'Month', quarter: 'Quarter', year: 'Year'};
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const svgNode = (tag, attributes = {}) => {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
  };
  const kpiCard = (label, value, note, kind = '') => {
    const card = node('article', undefined, `nq-kpi${kind ? ` nq-kpi-${kind}` : ''}`);
    card.append(node('span', label, 'nq-kpi-label'), node('strong', value), node('span', note, 'nq-kpi-note'));
    return card;
  };
  const days = (value) => (value === null || value === undefined ? '—' : `${Number(value).toFixed(1)} d`);
  // One floating tooltip for the Progress View charts; it follows the pointer and hides when it leaves the chart.
  const chartTooltip = (() => {
    const tip = node('div', undefined, 'nq-chart-tooltip');
    tip.hidden = true;
    tip.setAttribute('role', 'tooltip');
    document.body.append(tip);
    const show = (event, title, rows) => {
      const heading = node('strong', title);
      const list = node('div', undefined, 'nq-chart-tooltip-rows');
      rows.forEach(([label, value, color]) => {
        const line = node('div');
        const swatch = node('span', '', 'nq-swatch');
        swatch.style.background = color || 'transparent';
        line.append(swatch, node('span', label), node('b', value));
        list.append(line);
      });
      tip.replaceChildren(heading, list);
      tip.hidden = false;
      const gap = 14;
      const box = tip.getBoundingClientRect();
      const x = event.clientX + gap + box.width > window.innerWidth ? event.clientX - gap - box.width : event.clientX + gap;
      const y = Math.min(window.innerHeight - box.height - 8, Math.max(8, event.clientY - box.height / 2));
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    };
    const hide = () => { tip.hidden = true; };
    window.addEventListener('scroll', hide, true);
    window.addEventListener('blur', hide);
    return {show, hide};
  })();
  // A donut chart with its legend; a click on a slice filters the calls.
  const donut = (distribution) => {
    const card = node('section', undefined, 'nq-pie');
    card.append(node('h3', distribution.label));
    const items = distribution.items.slice(0, 10);
    const total = items.reduce((sum, item) => sum + item.count, 0);
    const colorFor = (item, index) => (distribution.field === 'status' ? optionColor('status', item.value)
      : distribution.field === 'team' ? optionColor('team', item.value) : '') || PALETTE[index % PALETTE.length];
    const svg = svgNode('svg', {viewBox: '0 0 120 120', class: 'nq-pie-chart', role: 'img', 'aria-label': distribution.label});
    const radius = 46;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;
    svg.append(svgNode('circle', {cx: 60, cy: 60, r: radius, fill: 'none', stroke: '#f3dfe6', 'stroke-width': 18}));
    items.forEach((item, index) => {
      const length = total ? (item.count / total) * circumference : 0;
      const slice = svgNode('circle', {
        cx: 60, cy: 60, r: radius, fill: 'none', stroke: colorFor(item, index), 'stroke-width': 18,
        'stroke-dasharray': `${length} ${circumference - length}`, 'stroke-dashoffset': -offset, transform: 'rotate(-90 60 60)',
      });
      slice.classList.add('nq-pie-slice');
      slice.addEventListener('pointermove', (event) => chartTooltip.show(event, distribution.label,
        [[item.value, `${number(item.count)} · ${percent(item.count, total)}`, colorFor(item, index)]]));
      slice.addEventListener('pointerleave', chartTooltip.hide);
      slice.addEventListener('click', () => {
        chartTooltip.hide();
        const field = {status: 'status', team: 'team', assignee: 'assignee', service: 'service', result: 'result'}[distribution.field];
        if (field) selectOnly(field, item.filter ?? (['Unassigned', '—'].includes(item.value) ? '' : item.value));
      });
      svg.append(slice);
      offset += length;
    });
    const centre = svgNode('text', {x: 60, y: 64, 'text-anchor': 'middle', class: 'nq-pie-total'});
    centre.textContent = number(total);
    svg.append(centre);
    const legend = node('ul', undefined, 'nq-pie-legend');
    items.forEach((item, index) => {
      const row = node('li');
      const button = node('button', undefined, 'nq-pie-item');
      button.type = 'button';
      const swatch = node('span', '', 'nq-swatch');
      swatch.style.background = colorFor(item, index);
      button.append(swatch, node('span', item.value, 'nq-pie-label'), node('strong', `${number(item.count)} · ${percent(item.count, total)}`));
      const filterField = {status: 'status', team: 'team', assignee: 'assignee', service: 'service', result: 'result'}[distribution.field];
      button.title = `Show only ${item.value}`;
      button.addEventListener('click', () => {
        const value = item.filter ?? (['Unassigned', '—'].includes(item.value) ? '' : item.value);
        selectOnly(filterField, value);
      });
      row.append(button);
      legend.append(row);
    });
    if (!items.length) legend.append(node('li', 'No calls.', 'nq-muted'));
    card.append(svg, legend);
    return card;
  };
  const statsTable = (table, columns, rows, {drillRow = null} = {}) => {
    const head = node('thead');
    const headRow = node('tr');
    columns.forEach((column) => headRow.append(node('th', column)));
    head.append(headRow);
    const body = node('tbody');
    rows.forEach((values, rowIndex) => {
      const row = node('tr');
      values.forEach((value, index) => row.append(node('td', value, index ? 'nq-number' : '')));
      const pairs = drillRow?.(rowIndex);
      if (pairs) {
        row.classList.add('nq-drill-row');
        row.classList.toggle('is-active', isDrilled(pairs));
        row.tabIndex = 0;
        row.title = 'Show only these calls; click again to remove the filter';
        row.addEventListener('click', () => drill(pairs));
        row.addEventListener('keydown', (event) => { if (event.key === 'Enter') drill(pairs); });
      }
      body.append(row);
    });
    if (!rows.length) {
      const row = node('tr');
      const cell = node('td', 'No data for this selection.', 'nq-empty');
      cell.colSpan = columns.length;
      row.append(cell);
      body.append(row);
    }
    table.replaceChildren(head, body);
  };
  // Detected, attended and closed calls per period, with the open backlog as a line.
  const timelineChart = (periods) => {
    const host = $('nq-timeline-chart');
    const shown = periods.slice(-24);
    if (!shown.length) { host.replaceChildren(node('p', 'No dated activity for this selection.', 'nq-muted')); return; }
    const series = [['detected', 'Detected', '#8a6b76'], ['attended', 'Attended', '#e08a1e'], ['closed', 'Closed', '#2e8b57']];
    const width = Math.max(640, shown.length * 64);
    const height = 240;
    const top = 16;
    const bottom = 40;
    const left = 40;
    const plot = height - top - bottom;
    const maximum = Math.max(1, ...shown.flatMap((period) => [...series.map(([key]) => period[key]), period.open_backlog]));
    const svg = svgNode('svg', {viewBox: `0 0 ${width + left} ${height}`, class: 'nq-timeline-svg', role: 'img', 'aria-label': 'Progress per period'});
    [0, 0.25, 0.5, 0.75, 1].forEach((share) => {
      const y = top + plot * (1 - share);
      svg.append(svgNode('line', {x1: left, x2: width + left, y1: y, y2: y, class: 'nq-grid-line'}));
      const label = svgNode('text', {x: left - 6, y: y + 4, 'text-anchor': 'end', class: 'nq-axis-label'});
      label.textContent = number(Math.round(maximum * share));
      svg.append(label);
    });
    const slot = width / shown.length;
    const bar = Math.min(16, (slot - 12) / series.length);
    const points = [];
    const zones = [];
    shown.forEach((period, index) => {
      const x = left + index * slot + (slot - bar * series.length) / 2;
      series.forEach(([key, label, color], position) => {
        const value = period[key];
        const barHeight = (value / maximum) * plot;
        svg.append(svgNode('rect', {x: x + position * bar, y: top + plot - barHeight, width: bar - 2, height: barHeight, rx: 2, fill: color}));
      });
      // The whole period column answers the pointer with every value of the period.
      const zone = svgNode('rect', {x: left + index * slot, y: top, width: slot, height: plot, class: 'nq-timeline-zone'});
      const rows = [...series.map(([key, label, color]) => [label, number(period[key]), color]), ['Open backlog', number(period.open_backlog), '#b0234f']];
      zone.addEventListener('pointermove', (event) => chartTooltip.show(event, period.period, rows));
      zone.addEventListener('pointerleave', chartTooltip.hide);
      zone.addEventListener('click', () => { chartTooltip.hide(); drill([['period', `${$('nq-granularity').value}:${period.period}`]]); });
      zones.push(zone);
      points.push(`${left + index * slot + slot / 2},${top + plot - (period.open_backlog / maximum) * plot}`);
      const caption = svgNode('text', {x: left + index * slot + slot / 2, y: height - bottom + 16, 'text-anchor': 'middle', class: 'nq-axis-label'});
      caption.textContent = period.period;
      svg.append(caption);
    });
    svg.append(svgNode('polyline', {points: points.join(' '), class: 'nq-backlog-line'}));
    points.forEach((point) => {
      const [cx, cy] = point.split(',');
      svg.append(svgNode('circle', {cx, cy, r: 3.5, class: 'nq-backlog-point'}));
    });
    svg.append(...zones);
    svg.addEventListener('pointerleave', chartTooltip.hide);
    const legend = node('div', undefined, 'nq-chart-legend');
    [...series, ['open_backlog', 'Open backlog', '#b0234f']].forEach(([, label, color]) => {
      const item = node('span');
      const swatch = node('span', '', 'nq-swatch');
      swatch.style.background = color;
      item.append(swatch, label);
      legend.append(item);
    });
    const scroller = node('div', undefined, 'nq-chart-scroll');
    scroller.append(svg);
    host.replaceChildren(legend, scroller);
    scroller.scrollLeft = scroller.scrollWidth;
  };
  const renderProgress = (progress) => {
    const summary = progress.summary;
    $('nq-progress-kpis').replaceChildren(
      drillCard(kpiCard('Attended', number(summary.attended), `${percent(summary.attended, summary.total)} have a follow-up`, 'open'), {pairs: [['state', 'attended']]}),
      drillCard(kpiCard('Not Attended', number(summary.not_attended), 'No change or comment yet', 'total'), {pairs: [['state', 'not_attended']]}),
      drillCard(kpiCard('Closure Rate', `${summary.closure_rate.toFixed(1)}%`, `${number(summary.closed)} of ${number(summary.total)} closed`, 'closed'), {pairs: [['state', 'closed']]}),
      drillCard(kpiCard('First Follow-up', days(summary.avg_days_to_first_follow_up), 'Average from the call', 'team'), {pairs: [['state', 'attended']]}),
      drillCard(kpiCard('Time to Close', days(summary.avg_days_to_close), 'Average from the first follow-up', 'commented'), {pairs: [['state', 'closed']]}),
      drillCard(kpiCard('Activity', number(summary.comments + summary.changes), `${number(summary.comments)} comments · ${number(summary.changes)} changes · ${number(summary.contributors)} users`), {pairs: [['state', 'attended']]}),
    );
    $('nq-pies').replaceChildren(...progress.distributions.map(donut));
    const label = GRANULARITY_LABELS[progress.granularity] || 'Month';
    $('nq-timeline-title').textContent = `Progress per ${label}`;
    timelineChart(progress.periods);
    const periods = [...progress.periods].reverse();
    statsTable($('nq-timeline-table'), [label, 'Detected', 'Attended', 'Comments', ...progress.statuses.map((status) => `→ ${status}`),
      'Closed', 'Reopened', 'Open Backlog', 'Avg Days to Close'],
    periods.map((period) => [period.period, number(period.detected), number(period.attended), number(period.comments),
      ...progress.statuses.map((status) => number(period.statuses[status] || 0)), number(period.closed), number(period.reopened),
      number(period.open_backlog), period.avg_days_to_close === null ? '—' : period.avg_days_to_close.toFixed(1)]),
    {drillRow: (index) => [['period', `${progress.granularity}:${periods[index].period}`]]});
    const agingTotal = progress.aging.reduce((sum, item) => sum + item.count, 0);
    const maxAge = Math.max(1, ...progress.aging.map((item) => item.count));
    $('nq-aging').replaceChildren(...progress.aging.map((item) => {
      const pairs = [['age', item.value], ['open_only', true]];
      const row = node('button', undefined, 'nq-bar');
      row.type = 'button';
      row.classList.toggle('is-active', isDrilled([pairs[0]]));
      row.title = `Show only the open calls ${item.value.toLowerCase()} old`;
      row.addEventListener('click', () => drill(pairs));
      const track = node('span', undefined, 'nq-bar-track');
      const fill = node('span', undefined, 'nq-bar-fill');
      fill.style.width = `${Math.max(2, (item.count / maxAge) * 100)}%`;
      track.append(fill);
      row.append(node('span', item.value, 'nq-bar-label'), track, node('span', `${number(item.count)} · ${percent(item.count, agingTotal)}`, 'nq-bar-count'));
      return row;
    }));
    const workload = (rows) => rows.map((row) => [row.name, number(row.open), number(row.closed), number(row.total)]);
    const person = (name) => (name === 'Unassigned' ? state.unassigned : name);
    statsTable($('nq-team-workload'), ['Team', 'Open', 'Closed', 'Total'], workload(progress.teams),
      {drillRow: (index) => [['team', person(progress.teams[index].name)]]});
    statsTable($('nq-assignee-workload'), ['Assignee', 'Open', 'Closed', 'Total'], workload(progress.assignees),
      {drillRow: (index) => [['assignee', person(progress.assignees[index].name)]]});
    statsTable($('nq-activity'), ['User', 'Changes', 'Comments', 'Calls Closed'],
      progress.activity.map((row) => [row.name, number(row.changes), number(row.comments), number(row.closed)]));
  };
  let progressToken = 0;
  async function loadProgress() {
    const token = ++progressToken;
    try {
      const progress = await api('/api/non-qualified-calls/progress', {
        method: 'POST', body: JSON.stringify({filters: currentFilters(), granularity: $('nq-granularity').value}),
      });
      if (token === progressToken) renderProgress(progress);
    } catch (error) {
      if (token === progressToken) $('nq-progress-kpis').replaceChildren(node('p', error.message, 'nq-muted'));
    }
  }
  $('nq-granularity').addEventListener('change', () => loadProgress());

  // -- root cause analysis ----------------------------------------------------------
  const staticBars = (title, items) => {
    // Items with drill pairs are buttons that filter the calls.
    const card = node('section', undefined, 'nq-breakdown');
    card.append(node('h3', title));
    const max = Math.max(1, ...items.map((item) => item.count));
    const total = items.reduce((sum, item) => sum + item.count, 0);
    if (!items.length) card.append(node('p', 'No calls.', 'form-note'));
    items.slice(0, 15).forEach((item) => {
      const row = node(item.pairs ? 'button' : 'div', undefined, item.pairs ? 'nq-bar' : 'nq-bar nq-static-bar');
      if (item.pairs) {
        row.type = 'button';
        row.classList.toggle('is-active', isDrilled(item.pairs));
        row.addEventListener('click', () => drill(item.pairs));
      }
      const track = node('span', undefined, 'nq-bar-track');
      const fill = node('span', undefined, 'nq-bar-fill');
      fill.style.width = `${Math.max(2, (item.count / max) * 100)}%`;
      if (item.color) fill.style.background = item.color;
      track.append(fill);
      row.title = item.pairs ? `${item.label}: show only these calls; click again to remove the filter` : item.label;
      row.append(node('span', item.label, 'nq-bar-label'), track, node('span', `${number(item.count)} · ${percent(item.count, total)}`, 'nq-bar-count'));
      card.append(row);
    });
    return card;
  };
  // The filter of a root domain or domain·cause, counting the suggestions as the panel does.
  const domainPair = (domain) => ($('nq-root-suggestions').checked
    ? ['effective_domain', domain === NOT_CLASSIFIED ? state.unassigned : domain]
    : ['root_domain', domain === NOT_CLASSIFIED ? state.unassigned : domain]);
  const causePair = (domain, cause) => [$('nq-root-suggestions').checked ? 'effective_cause' : 'root_pair', `${domain}||${cause}`];
  // Calls of every group per root domain, each domain with its colour; a group or a cell filters its calls.
  const domainTable = (table, title, rows, columns, colors, groupPair = null) => {
    const head = node('thead');
    const headRow = node('tr');
    headRow.append(node('th', title));
    columns.forEach((column) => {
      const cell = node('th', undefined, 'nq-root-domain-head');
      const swatch = node('span', '', 'nq-swatch');
      swatch.style.background = colors[column] || '#b8c0c6';
      cell.append(swatch, column);
      headRow.append(cell);
    });
    headRow.append(node('th', 'Total'));
    head.append(headRow);
    const body = node('tbody');
    const drillCell = (cell, pairs, title) => {
      if (!pairs) return cell;
      cell.classList.add('nq-drill-cell');
      cell.classList.toggle('is-active', isDrilled(pairs));
      cell.tabIndex = 0;
      cell.title = `${title}: show only these calls; click again to remove the filter`;
      cell.addEventListener('click', () => drill(pairs));
      cell.addEventListener('keydown', (event) => { if (event.key === 'Enter') drill(pairs); });
      return cell;
    };
    rows.forEach((row) => {
      const line = node('tr');
      const group = groupPair?.(row.name);
      line.append(drillCell(node('td', row.name), group && [group], row.name));
      columns.forEach((column) => {
        const count = row.counts[column];
        line.append(drillCell(node('td', count ? number(count) : '—', 'nq-number'), group && count ? [group, domainPair(column)] : null,
          `${row.name} · ${column}`));
      });
      line.append(drillCell(node('td', number(row.total), 'nq-number'), group && [group], row.name));
      body.append(line);
    });
    if (!rows.length) {
      const line = node('tr');
      const cell = node('td', 'No data for this selection.', 'nq-empty');
      cell.colSpan = columns.length + 2;
      line.append(cell);
      body.append(line);
    }
    table.replaceChildren(head, body);
  };
  const renderRootCauses = (stats) => {
    const summary = stats.summary;
    $('nq-root-kpis').replaceChildren(
      drillCard(kpiCard('Calls', number(summary.total), 'Non-Qualified Calls of the selection', 'total'),
        {clear: ['rca_state', 'state', 'effective_domain', 'effective_cause', 'root_pair']}),
      drillCard(kpiCard('Labelled', number(summary.labelled), `${percent(summary.labelled, summary.total)} have a root cause`, 'closed'), {pairs: [['state', 'labelled']]}),
      drillCard(kpiCard('Suggested', number(summary.suggested), stats.include_suggestions ? 'Counted with their suggested root cause' : 'Not counted', 'team'), {pairs: [['rca_state', 'suggested']]}),
      drillCard(kpiCard(NOT_CLASSIFIED, number(summary.unclassified), `${percent(summary.unclassified, summary.total)} without a root cause`, 'open'), {pairs: [domainPair(NOT_CLASSIFIED)]}),
    );
    $('nq-root-breakdowns').replaceChildren(
      staticBars('By Root Domain', stats.domains.map((item) => ({label: item.value, count: item.count, color: item.color,
        pairs: [domainPair(item.value)]}))),
      staticBars('By Root Cause', stats.causes.map((item) => ({label: `${item.domain} · ${item.cause}`, count: item.count, color: item.color,
        pairs: [causePair(item.domain, item.value ?? '')]}))),
    );
    const colors = Object.fromEntries(stats.domains.map((item) => [item.value, item.color]));
    domainTable($('nq-root-call-types'), 'Call Type', stats.call_types, stats.columns, colors, (name) => ['call_type', name]);
    domainTable($('nq-root-nr-modes'), 'NR Mode', stats.nr_modes, stats.columns, colors, (name) => ['nr_mode', name === 'Unknown' ? state.unassigned : name]);
    // Technologies are a filter of the Filters panel; calls without a technology cannot be selected there.
    domainTable($('nq-root-technologies'), 'Technology', stats.technologies, stats.columns, colors,
      (name) => (name === 'Unknown' ? null : ['technology', name]));
    statsTable($('nq-root-nodes'), ['eNB / gNB', 'Operator', 'Site', 'Host', 'Vendor', 'Calls', 'Main Domain'],
      stats.nodes.map((row) => [row.node, row.operator, row.site || '—', row.host || '—', row.vendor || '—', number(row.calls), row.top_domain || '—']),
      {drillRow: (index) => [['node', `${stats.nodes[index].operator}||${stats.nodes[index].node}`]]});
    // Only the call count is a number: the other columns are names.
    $('nq-root-nodes').querySelectorAll('tbody td.nq-number').forEach((cell) => {
      if (cell.cellIndex !== 5) cell.classList.remove('nq-number');
    });
  };
  let rootToken = 0;
  async function loadRootCauses() {
    const token = ++rootToken;
    try {
      const stats = await api('/api/non-qualified-calls/root-causes/stats', {
        method: 'POST', body: JSON.stringify({filters: currentFilters(), include_suggestions: $('nq-root-suggestions').checked}),
      });
      if (token === rootToken) renderRootCauses(stats);
    } catch (error) {
      if (token === rootToken) $('nq-root-kpis').replaceChildren(node('p', error.message, 'nq-muted'));
    }
  }
  $('nq-root-suggestions').addEventListener('change', () => loadRootCauses());

  // -- lifecycle & phases (Analysis Center) ---------------------------------------------------
  // A Status Rule in words: "Analysis Status is Finished and Planned Status is not Planned".
  const conditionText = (condition) => {
    const label = state.conditionFields[condition.field]?.label || condition.field;
    const values = condition.values || [];
    if (condition.op === 'empty') return `${label} is empty`;
    if (condition.op === 'not_empty') return `${label} is not empty`;
    const verb = condition.op === 'not_in' ? (values.length > 1 ? 'is not one of' : 'is not') : (values.length > 1 ? 'is one of' : 'is');
    return `${label} ${verb} ${values.join(', ')}`;
  };
  // The calls that meet a Status Rule: each condition becomes the filter of its field.
  const CONDITION_FILTERS = {'@team': 'team', '@assignee': 'assignee', '@root_category': 'root_category', '@root_cause': 'root_cause'};
  const applyRuleFilters = (rule, index) => {
    rule.conditions.forEach((condition) => {
      if (condition.field === '@attended') {
        state.extraFilters.state = [condition.values.includes('Yes') === (condition.op === 'in') ? 'attended' : 'not_attended'];
        return;
      }
      const select = root.querySelector(`[data-nq-filter="${CSS.escape(CONDITION_FILTERS[condition.field] || `field:${condition.field}`)}"]`);
      if (!select) return;
      const values = new Set(condition.values);
      [...select.options].forEach((option) => {
        const empty = option.value === state.unassigned;
        option.selected = condition.op === 'in' ? values.has(option.value) : condition.op === 'not_in' ? !values.has(option.value)
          : condition.op === 'empty' ? empty : !empty;
      });
      select.dispatchEvent(new Event('multiselect:options-updated'));
    });
    toast(`Showing the calls that meet rule ${index + 1}${state.view === 'dashboards' ? ': open Calls to see them' : ''}.`);
    scheduleLoad();
  };
  // What moves a call to a status: each rule as chips, the field name and its values in their colours.
  const ruleTriggers = (status, rules) => {
    const host = node('div', undefined, 'nq-triggers');
    rules.forEach((rule, index) => {
      if (rule.status !== status) return;
      const trigger = node('button', undefined, 'nq-trigger');
      trigger.type = 'button';
      trigger.title = `Rule ${index + 1} of the Status Rules (tried in this order): ${rule.conditions.map(conditionText).join(' and ')}.\n`
        + 'Click to show the calls that meet it.';
      trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        applyRuleFilters(rule, index);
      });
      trigger.append(node('span', `Rule ${index + 1}`, 'nq-rule-number'));
      rule.conditions.forEach((condition, position) => {
        if (position) trigger.append(node('span', '+', 'nq-trigger-and'));
        const label = state.conditionFields[condition.field]?.label || condition.field;
        if (condition.field === '@attended') {
          trigger.append(node('span', condition.values.includes('No') && condition.op === 'in' ? 'Not attended' : 'Attended', 'nq-trigger-field'));
          return;
        }
        trigger.append(node('span', label, 'nq-trigger-field'));
        if (condition.op === 'empty' || condition.op === 'not_empty') {
          trigger.append(node('span', condition.op === 'empty' ? 'empty' : 'set', 'nq-trigger-op'));
          return;
        }
        if (condition.op === 'not_in') trigger.append(node('span', 'not', 'nq-trigger-op'));
        condition.values.forEach((value) => {
          const chip = node('span', value, 'nq-pill nq-trigger-value');
          paintPill(chip, conditionColor(condition.field, value));
          trigger.append(chip);
        });
      });
      host.append(trigger);
    });
    if (status === state.options.statuses[0]?.name) host.append(node('div', 'When no rule applies', 'nq-trigger is-fallback'));
    return host.childElementCount ? host : null;
  };
  // A bar split in the share of each value, in its colour.
  const stackedBar = (items, total) => {
    const bar = node('div', undefined, 'nq-stacked-bar');
    items.filter((item) => item.count).forEach((item) => {
      const part = node('span');
      part.style.flexGrow = String(item.count);
      part.style.background = item.color || '#d9cfd3';
      part.title = `${item.label}: ${number(item.count)} · ${percent(item.count, total)}`;
      bar.append(part);
    });
    if (!total) bar.classList.add('is-empty');
    return bar;
  };
  const renderLifecycle = (life) => {
    const total = life.total;
    const closed = life.pipeline.filter((item) => item.closed).reduce((sum, item) => sum + item.count, 0);
    $('nq-life-kpis').replaceChildren(
      drillCard(kpiCard('Calls', number(total), 'Non-Qualified Calls of the selection', 'total'), {clear: ['status_mode']}),
      drillCard(kpiCard('Automatic Status', number(life.modes.auto), `${percent(life.modes.auto, total)} follow the Status Rules`, 'team'),
        {pairs: [['status_mode', 'auto']]}),
      drillCard(kpiCard('Status by Hand', number(life.modes.manual), `${percent(life.modes.manual, total)} chosen by an analyst`, 'commented'),
        {pairs: [['status_mode', 'manual']]}),
      drillCard(kpiCard('Open', number(total - closed), `${percent(total - closed, total)} still in follow-up`, 'open'), {pairs: [['open_only', true]]}),
      drillCard(kpiCard('Closed', number(closed), `${percent(closed, total)} closed`, 'closed'), {pairs: [['state', 'closed']]}),
      kpiCard('Stalled', number(life.stalled_total), `Open, no change for ${life.stalled_days}+ days`, 'attended'),
    );
    // The pipeline: the open statuses in order, then the closed ones.
    const steps = [...life.pipeline.filter((item) => !item.closed), ...life.pipeline.filter((item) => item.closed)];
    const pipeline = $('nq-life-pipeline');
    pipeline.replaceChildren(stackedBar(steps.map((item) => ({label: item.status, count: item.count, color: item.color})), total));
    const flow = node('div', undefined, 'nq-pipeline-steps');
    steps.forEach((item, index) => {
      if (index && !item.closed) flow.append(node('span', '→', 'nq-pipeline-arrow'));
      if (item.closed && !steps[index - 1]?.closed && index) flow.append(node('span', '⇒', 'nq-pipeline-arrow is-closing'));
      const step = node('button', undefined, `nq-pipeline-step${item.closed ? ' is-closed' : ''}`);
      step.type = 'button';
      step.style.setProperty('--nq-step', item.color || '#b8c0c6');
      const filters = currentFilters();
      step.classList.toggle('is-active', (filters.status || []).length === 1 && filters.status[0] === item.status);
      step.append(node('span', item.status, 'nq-pipeline-name'), node('strong', number(item.count)),
        node('span', `${percent(item.count, total)}${item.avg_age_days === null ? '' : ` · ${item.avg_age_days} d old on average`}`, 'nq-kpi-note'));
      const triggers = ruleTriggers(item.status, life.rules || []);
      if (triggers) step.append(triggers);
      step.title = `Show only the calls ${item.status}`;
      step.addEventListener('click', () => selectOnly('status', item.status));
      flow.append(step);
    });
    pipeline.append(flow);
    // RCA Identification, then one card per phase field: how its values split the calls.
    const rcaPhase = life.rca && state.sections.some((section) => section.key === 'rca') ? [{
      key: '', label: 'RCA Identification', section: 'rca', empty: 0, drill: 'state',
      items: [{value: 'Identified', count: life.rca.identified, color: '#2e8b57', filter: 'identified'},
        {value: 'Not identified', count: life.rca.not_identified, color: '#e7dde1', filter: 'not_identified'}],
    }] : [];
    $('nq-life-phases').replaceChildren(...[...rcaPhase, ...life.phases].map((phase) => {
      const section = sectionOf(phase.section);
      const card = node('section', undefined, 'nq-phase-card');
      card.style.setProperty('--nq-section', section.color);
      const head = node('header');
      head.append(sectionTag(phase.section), node('h3', phase.label));
      const items = phase.drill ? phase.items.map((item) => ({label: item.value, value: item.filter, count: item.count, color: item.color}))
        : [...phase.items.map((item) => ({label: item.value, value: item.value, count: item.count, color: item.color})),
          {label: 'Empty', value: '', count: phase.empty, color: '#e7dde1'}];
      const field = phase.drill || `field:${phase.key}`;
      const rows = node('div', undefined, 'nq-phase-values');
      items.forEach((item) => {
        const pairs = [[field, item.value || state.unassigned]];
        const row = node('button', undefined, 'nq-phase-value');
        row.type = 'button';
        row.classList.toggle('is-active', isDrilled(pairs));
        const swatch = node('span', '', 'nq-swatch');
        swatch.style.background = item.color || '#d9cfd3';
        row.append(swatch, node('span', item.label, 'nq-bar-label'), node('strong', number(item.count)),
          node('span', percent(item.count, total), 'nq-muted'));
        row.title = `Show only the calls with ${phase.label}: ${item.label}`;
        row.addEventListener('click', () => drill(pairs));
        rows.append(row);
      });
      card.append(head, stackedBar(items, total), rows);
      return card;
    }));
    if (!life.phases.length) $('nq-life-phases').append(node('p', 'No list field in the Analysis, Implementation or Planning sections.', 'nq-muted'));
    statsTable($('nq-life-times'), ['Status', 'Average Days', 'Calls Moved Out'],
      life.time_in_status.map((item) => [item.status, item.avg_days.toFixed(1), number(item.moves)]),
      {drillRow: (index) => [['status', life.time_in_status[index].status]]});
    statsTable($('nq-life-moves'), ['From', 'To', 'Times'], life.moves.map((item) => [item.from, item.to, number(item.count)]));
    $('nq-life-moves').querySelectorAll('tbody td:nth-child(2)').forEach((cell) => cell.classList.remove('nq-number'));
    $('nq-life-stalled-title').textContent = `Stalled Open Calls · no change for ${life.stalled_days}+ days (${number(life.stalled_total)})`;
    statsTable($('nq-life-stalled'), ['Status', 'Operator', 'Campaign', 'City', 'Days Without Change', 'Followed Up'],
      life.stalled.map((item) => [item.status, item.operator || '—', campaignLabel(item.campaign) || '—', item.city || '—',
        number(item.days), item.followed_up ? 'Yes' : 'Not yet']));
    // Each stalled call opens on a click.
    [...$('nq-life-stalled').tBodies[0].rows].forEach((row, index) => {
      const item = life.stalled[index];
      if (!item) return;
      [...row.cells].forEach((cell, position) => { if (position && position !== 4) cell.classList.remove('nq-number'); });
      row.classList.add('nq-drill-row');
      row.tabIndex = 0;
      row.title = 'Open this call';
      row.addEventListener('click', () => openDetail(item.call_key));
      row.addEventListener('keydown', (event) => { if (event.key === 'Enter') openDetail(item.call_key); });
    });
  };
  let lifeToken = 0;
  async function loadLifecycle() {
    const token = ++lifeToken;
    try {
      const life = await api('/api/non-qualified-calls/lifecycle', {method: 'POST', body: JSON.stringify({filters: currentFilters()})});
      if (token === lifeToken) renderLifecycle(life);
    } catch (error) {
      if (token === lifeToken) $('nq-life-kpis').replaceChildren(node('p', error.message, 'nq-muted'));
    }
  }

  // -- root cause sources (Analysis Center) ---------------------------------------------------
  // A category → cause tree of one source; the analysts' choices filter the calls.
  const hierarchyCard = (title, note, groups, drillable) => {
    const card = node('section', undefined, 'nq-breakdown nq-hierarchy');
    card.append(node('h3', title), node('p', note, 'nq-muted nq-hierarchy-note'));
    const max = Math.max(1, ...groups.map((group) => group.count));
    if (!groups.length) card.append(node('p', 'No calls.', 'form-note'));
    groups.forEach((group) => {
      const category = group.category === '—' ? '' : group.category;
      const color = drillable ? optionColor('root_category', category) : '';
      const pairs = drillable ? [['root_category', category || state.unassigned]] : null;
      card.append(hierarchyRow(group.category === '—' ? (drillable ? NOT_CLASSIFIED : 'No category') : group.category,
        group.count, max, color, pairs, 'is-category'));
      group.causes.forEach((item) => {
        const cause = item.cause === '—' ? '' : item.cause;
        const causePairs = drillable ? [...pairs, ['root_cause', cause || state.unassigned]] : null;
        card.append(hierarchyRow(item.cause === '—' ? NO_CAUSE : item.cause, item.count, max, color, causePairs, 'is-cause'));
      });
    });
    return card;
  };
  const hierarchyRow = (label, count, max, color, pairs, kind) => {
    const row = node(pairs ? 'button' : 'div', undefined, `nq-bar nq-hierarchy-row ${kind}${pairs ? '' : ' nq-static-bar'}`);
    if (pairs) {
      row.type = 'button';
      row.classList.toggle('is-active', isDrilled(pairs));
      row.addEventListener('click', () => drill(pairs));
      row.title = `${label}: show only these calls; click again to remove the filter`;
    } else {
      row.title = label;
    }
    const track = node('span', undefined, 'nq-bar-track');
    const fill = node('span', undefined, 'nq-bar-fill');
    fill.style.width = `${Math.max(2, (count / max) * 100)}%`;
    if (color) fill.style.background = color;
    track.append(fill);
    row.append(node('span', label, 'nq-bar-label'), track, node('span', number(count), 'nq-bar-count'));
    return row;
  };
  // How the categories one RCA source maps to relate to the Root Categories the analysts selected.
  const renderMatrix = (insights) => {
    const matrix = insights.confusion[state.matrixSource] || {rows: [], columns: [], cells: []};
    const tabs = $('nq-sources-matrix-tabs');
    tabs.replaceChildren(...[['script', 'RCA Script'], ['netcheck', 'NetCheck']].map(([source, label]) => {
      const tab = node('button', label, 'nq-rate-tab');
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(source === state.matrixSource));
      tab.classList.toggle('is-active', source === state.matrixSource);
      tab.addEventListener('click', () => { state.matrixSource = source; renderMatrix(insights); });
      return tab;
    }));
    const table = $('nq-sources-matrix');
    const head = node('thead');
    const headRow = node('tr');
    headRow.append(node('th', `${state.matrixSource === 'script' ? 'RCA Script' : 'NetCheck'} ↓ · Selected →`));
    matrix.columns.forEach((column) => headRow.append(node('th', column)));
    head.append(headRow);
    const body = node('tbody');
    const highest = Math.max(1, ...matrix.cells.flat());
    matrix.rows.forEach((name, rowIndex) => {
      const row = node('tr');
      row.append(node('th', name));
      matrix.columns.forEach((column, columnIndex) => {
        const count = matrix.cells[rowIndex][columnIndex];
        const cell = node('td', count ? number(count) : '·', `nq-number nq-matrix-cell${name === column ? ' is-match' : ''}`);
        if (count) cell.style.background = heat(count, highest)[0];
        cell.title = `${name} → ${column}: ${number(count)} calls${name === column ? ' (the analysts agree)' : ''}`;
        row.append(cell);
      });
      body.append(row);
    });
    if (!matrix.rows.length) {
      const row = node('tr');
      const cell = node('td', 'No call has both a proposal of this source and a selected root category yet.', 'nq-empty');
      cell.colSpan = Math.max(2, matrix.columns.length + 1);
      row.append(cell);
      body.append(row);
    }
    table.replaceChildren(head, body);
  };
  const renderSources = (insights) => {
    const {coverage, agreement} = insights;
    const results = insights.rca_results || {};
    $('nq-sources-results').textContent = results.total
      ? `${number(results.total)} RCA script results · ${number(results.matched)} match calls` : 'No RCA script results imported yet';
    const rate = (item) => (item.rate === null ? '—' : `${item.rate.toFixed(1)}%`);
    $('nq-sources-kpis').replaceChildren(
      kpiCard('Calls', number(coverage.total), 'Non-Qualified Calls of the selection', 'total'),
      kpiCard('RCA Script', number(coverage.script), `${percent(coverage.script, coverage.total)} have script results`, 'attended'),
      kpiCard('NetCheck RCA', number(coverage.netcheck), `${percent(coverage.netcheck, coverage.total)} classified by NetCheck`, 'team'),
      kpiCard('Selected', number(coverage.selected), `${percent(coverage.selected, coverage.total)} have a root category or cause`, 'closed'),
      kpiCard('Script ↔ Selected', rate(agreement.selected_script), `${number(agreement.selected_script.agree)} of ${number(agreement.selected_script.compared)} calls agree`, 'commented'),
      kpiCard('NetCheck ↔ Selected', rate(agreement.selected_netcheck), `${number(agreement.selected_netcheck.agree)} of ${number(agreement.selected_netcheck.compared)} calls agree`, 'commented'),
      kpiCard('Script ↔ NetCheck', rate(agreement.script_netcheck), `${number(agreement.script_netcheck.agree)} of ${number(agreement.script_netcheck.compared)} calls agree`, 'open'),
    );
    $('nq-sources-hierarchies').replaceChildren(
      hierarchyCard('RCA Script', 'Suggested Category → Cause of the script', insights.hierarchies.script, false),
      hierarchyCard('NetCheck RCA', 'Failure Category → Subcategory of the CDR', insights.hierarchies.netcheck, false),
      hierarchyCard('Selected by the Analysts', 'Root Category → Root Cause; click to drill down', insights.hierarchies.selected, true),
    );
    $('nq-sources-domains').replaceChildren(staticBars('Selected Root Domains', insights.domains.map((item) => ({
      label: item.domain, count: item.count, color: item.color,
      pairs: [['root_domain', item.domain === NOT_CLASSIFIED ? state.unassigned : item.domain]],
    }))));
    renderMatrix(insights);
  };
  let sourcesToken = 0;
  async function loadSources() {
    const token = ++sourcesToken;
    try {
      const insights = await api('/api/non-qualified-calls/rca/insights', {method: 'POST', body: JSON.stringify({filters: currentFilters()})});
      if (token === sourcesToken) renderSources(insights);
    } catch (error) {
      if (token === sourcesToken) $('nq-sources-kpis').replaceChildren(node('p', error.message, 'nq-muted'));
    }
  }

  async function loadState() {
    try {
      const payload = await api('/api/non-qualified-calls/state');
      state.options = payload.options;
      state.rootCauses = payload.root_causes || state.rootCauses;
      state.rootCauseDefaults = payload.root_cause_defaults || {domains: [], categories: [], causes: []};
      state.ruleFields = payload.root_cause_rule_fields || {};
      state.defaultRule = payload.default_root_cause_rule || null;
      state.users = payload.users || [];
      state.user = payload.user;
      state.unassigned = payload.unassigned || state.unassigned;
      state.datasets = payload.datasets || [];
      state.mainCities = payload.main_cities || [];
      state.fields = payload.fields || [];
      state.fieldTypes = payload.field_types || {};
      state.fieldSources = payload.field_sources || {};
      state.trackingRefs = payload.tracking_refs || {};
      state.rcaRefs = payload.rca_refs || {};
      state.callFields = payload.call_fields || [];
      state.sections = payload.sections || [];
      state.defaultSections = payload.default_sections || [];
      state.statusRules = payload.status_rules || [];
      state.defaultStatusRules = payload.default_status_rules || [];
      state.defaultOptions = payload.default_options || {statuses: [], teams: []};
      state.ruleOperators = payload.rule_operators || {};
      state.conditionFields = payload.condition_fields || {};
      state.rcaResults = payload.rca_results || {};
      state.rcaSources = payload.rca_sources || {};
      buildDrawerTabs();
      state.tableColumns = payload.table_columns || {builtin: [], cdr: []};
      state.optionalColumns = payload.optional_columns || {};
      state.cdrColumns = payload.cdr_columns || [];
      state.maxCdrColumns = payload.max_cdr_columns || 12;
      state.versionLabels = payload.version_labels || {};
      renderDynamicHeaders();
      renderSync(payload.sync);
      fillFilters(payload);
      if (!state.filtersRestored) {
        state.filtersRestored = true;
        applySavedFilters(payload.saved_filters || {});
      }
      fillBulkSelects();
      if ($('nq-bulk-history')) $('nq-bulk-history').hidden = !state.user.can_moderate;
      await loadCalls();
    } catch (error) {
      $('nq-sync').textContent = error.message;
      $('nq-count').textContent = error.message;
    }
  }

  // -- NQ rate by campaign and operator -------------------------------------------------
  // A pastel colour from soft mint (no NQ calls) through apricot to dusty rose (the highest rate of the matrix).
  const heat = (rate, highest) => {
    if (rate === null || rate === undefined) return ['#f7f2f4', 'var(--nq-muted)'];
    const share = highest > 0 ? Math.min(1, rate / highest) : 0;
    const low = [0xee, 0xf6, 0xef];
    const mid = [0xfb, 0xe0, 0xbd];
    const high = [0xeb, 0x95, 0xaa];
    const [start, end, step] = share < 0.5 ? [low, mid, share * 2] : [mid, high, (share - 0.5) * 2];
    const rgb = start.map((value, index) => Math.round(value + (end[index] - value) * step));
    const luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
    return [`rgb(${rgb.join(', ')})`, luminance < 0.55 ? '#fff' : '#3d1824'];
  };
  const rateText = (cell) => (cell && cell.rate !== null && cell.rate !== undefined ? `${Number(cell.rate).toFixed(1)}%` : '—');
  const renderRates = (rates) => {
    const matrices = rates.matrices || [];
    const tabs = $('nq-rate-tabs');
    if (!matrices.some((matrix) => matrix.service === state.rateService)) {
      state.rateService = (matrices.find((matrix) => matrix.service === 'voice') || matrices[0])?.service || '';
    }
    tabs.replaceChildren(...matrices.map((matrix) => {
      const tab = node('button', matrix.label, 'nq-rate-tab');
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(matrix.service === state.rateService));
      tab.classList.toggle('is-active', matrix.service === state.rateService);
      tab.addEventListener('click', () => { state.rateService = matrix.service; renderRates(rates); });
      return tab;
    }));
    const matrix = matrices.find((item) => item.service === state.rateService);
    const table = $('nq-rate-table');
    if (!matrix || !matrix.campaigns.length) {
      $('nq-rate-overview').replaceChildren(node('p', 'No calls for this selection.', 'nq-muted'));
      table.replaceChildren();
      $('nq-rate-legend').replaceChildren();
      return;
    }
    const total = matrix.total;
    const operatorCards = matrix.operators.map((operator) => {
      const cell = matrix.operator_totals[operator];
      const card = node('article', undefined, 'nq-rate-card');
      // The operator's name in its Operator Maps colour.
      const label = node('span', operator, 'nq-rate-operator');
      if (matrix.operator_colors?.[operator]) label.style.color = matrix.operator_colors[operator];
      card.append(label, node('strong', rateText(cell)),
        node('span', `${number(cell?.nq)} of ${number(cell?.total)} calls`, 'nq-kpi-note'));
      const meter = node('span', undefined, 'nq-rate-meter');
      const fill = node('span');
      fill.style.width = `${Math.min(100, Number(cell?.rate || 0) * (100 / Math.max(1, ...matrix.operators.map((name) => Number(matrix.operator_totals[name]?.rate || 0)))))}%`;
      fill.style.background = heat(cell?.rate, Math.max(...matrix.operators.map((name) => Number(matrix.operator_totals[name]?.rate || 0))))[0];
      meter.append(fill);
      card.append(meter);
      return drillCard(card, {pairs: [['operator', operator]]});
    });
    const overall = node('article', undefined, 'nq-rate-card nq-rate-card-total');
    overall.append(node('span', 'Overall', 'nq-rate-operator'), node('strong', rateText(total)),
      node('span', `${number(total.nq)} Non-Qualified of ${number(total.total)} calls`, 'nq-kpi-note'));
    $('nq-rate-overview').replaceChildren(overall, ...operatorCards);
    const highest = Math.max(0, ...matrix.campaigns.flatMap((campaign) => Object.values(matrix.cells[campaign] || {}).map((cell) => Number(cell.rate || 0))));
    const head = node('thead');
    const headRow = node('tr');
    headRow.append(node('th', 'Campaign'), ...matrix.operators.map((operator) => node('th', operator)), node('th', 'Total'));
    head.append(headRow);
    const body = node('tbody');
    const cellOf = (cell, pairs, title, isTotal = false) => {
      const td = node('td', undefined, `nq-rate-cell${isTotal ? ' is-total' : ''}`);
      const [fill, ink] = heat(cell?.rate, highest);
      const box = node(pairs ? 'button' : 'div', undefined, 'nq-rate-box');
      if (pairs) {
        box.type = 'button';
        box.classList.toggle('is-active', isDrilled(pairs));
        box.addEventListener('click', () => drill(pairs));
      }
      box.style.background = isTotal ? '' : fill;
      box.style.color = isTotal ? '' : ink;
      box.append(node('strong', rateText(cell)), node('span', cell ? `${number(cell.nq)} / ${number(cell.total)}` : 'No calls'));
      box.title = cell ? `${title}: ${number(cell.nq)} Non-Qualified of ${number(cell.total)} calls (${rateText(cell)})` : `${title}: no calls`;
      td.append(box);
      return td;
    };
    matrix.campaigns.forEach((campaign) => {
      const row = node('tr');
      row.append(node('th', campaignLabel(campaign), 'nq-rate-campaign'));
      matrix.operators.forEach((operator) => {
        const cell = matrix.cells[campaign]?.[operator];
        row.append(cellOf(cell, cell ? [['campaign', campaign], ['operator', operator]] : null, `${campaignLabel(campaign)} · ${operator}`));
      });
      row.append(cellOf(matrix.campaign_totals[campaign], [['campaign', campaign]], campaignLabel(campaign), true));
      body.append(row);
    });
    const totals = node('tr', undefined, 'nq-rate-totals');
    totals.append(node('th', 'Total'), ...matrix.operators.map((operator) => cellOf(matrix.operator_totals[operator],
      [['operator', operator]], operator, true)), cellOf(total, null, 'Every call', true));
    body.append(totals);
    table.replaceChildren(head, body);
    const legend = $('nq-rate-legend');
    const scale = node('span', undefined, 'nq-rate-scale');
    scale.style.background = `linear-gradient(90deg, ${heat(0, 1)[0]}, ${heat(0.5, 1)[0]}, ${heat(1, 1)[0]})`;
    legend.replaceChildren(node('span', '0%'), scale, node('span', `${highest.toFixed(1)}% (highest of the table)`),
      node('span', 'Each cell: NQ rate · Non-Qualified / all calls', 'nq-muted'));
  };
  let rateToken = 0;
  // The NQ rate depends only on these filters and on the indexed CDRs: other filter changes keep it.
  const RATE_FILTER_KEYS = ['datasets', 'service', 'campaign', 'operator', 'nr_mode'];
  let rateKey = '';
  async function loadRates() {
    const filters = currentFilters();
    const rateFilters = Object.fromEntries(RATE_FILTER_KEYS.filter((key) => key in filters).map((key) => [key, filters[key]]));
    const key = JSON.stringify([rateFilters, state.result?.sync?.synced_at || '']);
    if (key === rateKey) return;
    rateKey = key;
    const token = ++rateToken;
    try {
      const rates = await api('/api/non-qualified-calls/rates', {method: 'POST', body: JSON.stringify({filters: rateFilters})});
      if (token === rateToken) renderRates(rates);
    } catch (error) {
      if (token === rateToken) {
        rateKey = '';
        $('nq-rate-overview').replaceChildren(node('p', error.message, 'nq-muted'));
      }
    }
  }

  // -- call detail drawer -------------------------------------------------------
  const drawer = $('nq-drawer');
  const backdrop = $('nq-drawer-backdrop');
  const closeDrawer = () => {
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    backdrop.hidden = true;
    state.detail = null;
  };
  const selectTab = (name) => {
    if (!drawer.querySelector(`[data-nq-tab="${CSS.escape(name)}"]`)) name = 'general';
    drawer.querySelectorAll('[data-nq-tab]').forEach((tab) => {
      const active = tab.dataset.nqTab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
      // Where the tabs scroll sideways (phones), the chosen one comes into view.
      if (active && tab.parentElement.scrollWidth > tab.parentElement.clientWidth) {
        tab.parentElement.scrollLeft = tab.offsetLeft - (tab.parentElement.clientWidth - tab.offsetWidth) / 2;
      }
    });
    drawer.querySelectorAll('[data-nq-panel]').forEach((panel) => { panel.hidden = panel.dataset.nqPanel !== name; });
  };
  // One tab per section of the Analysis Center, in its colour, then the call details; the General
  // tab holds the activity of the call and every other section its own panel of fields.
  // The tabs of a call: the activity (the General section), then one per section, Implementation and Planning together.
  const TAB_GROUPS = [['general'], ['rca'], ['failure_event'], ['analysis'], ['implementation', 'planning']];
  // The call details close the tabs, in grey.
  const CALL_DETAILS_COLOR = '#9aa5ad';
  const drawerTabs = () => {
    const known = new Set(state.sections.map((section) => section.key));
    const grouped = new Set(TAB_GROUPS.flat());
    return [...TAB_GROUPS, ...state.sections.filter((section) => !grouped.has(section.key)).map((section) => [section.key])]
      .map((keys) => keys.filter((key) => known.has(key))).filter((keys) => keys.length)
      .map((keys) => ({key: keys[0], sections: keys.map(sectionOf), color: sectionOf(keys[0]).color,
        label: keys[0] === 'general' ? 'Activity' : keys.map((key) => sectionOf(key).label).join(' & ')}));
  };
  const buildDrawerTabs = () => {
    const tabs = $('nq-drawer-tabs');
    const active = tabs.querySelector('.is-active')?.dataset.nqTab || 'general';
    const tab = (key, label, color) => {
      const button = node('button', undefined, 'nq-drawer-tab');
      button.type = 'button';
      button.setAttribute('role', 'tab');
      button.dataset.nqTab = key;
      if (color) button.style.setProperty('--nq-section', color);
      button.append(node('span', label), node('small', '', 'nq-tab-badge'));
      button.addEventListener('click', () => selectTab(key));
      return button;
    };
    const groups = state.sections.length ? drawerTabs() : [{key: 'general', label: 'Activity', color: '', sections: []}];
    tabs.replaceChildren(...groups.map((group) => tab(group.key, group.label, group.color)), tab('details', 'Call Details', CALL_DETAILS_COLOR));
    $('nq-section-panels').replaceChildren(...groups.filter((group) => group.key !== 'general').map((group) => {
      const panel = node('section', undefined, 'nq-section-panel');
      panel.dataset.nqPanel = group.key;
      panel.hidden = true;
      panel.style.setProperty('--nq-section', group.color);
      panel.append(node('div', undefined, 'nq-section-fields'));
      return panel;
    }));
    selectTab(active);
  };
  const timelineChange = (entry) => {
    const item = node('li', undefined, 'nq-event nq-event-change');
    item.append(node('span', '', 'nq-event-dot'));
    const text = node('p');
    const who = node('strong', entry.changed_by);
    if (entry.field === 'comment_edit') text.append(who, ' edited a comment');
    else if (entry.field === 'comment_delete') text.append(who, ' deleted a comment');
    else if (entry.field === 'status_mode') {
      text.append(who, entry.new_value === 'auto' ? ' gave the status back to the Status Rules' : ' set the status by hand');
    } else {
      const kind = entry.field;
      const emptyLabel = kind === 'root_cause' ? NO_CAUSE : kind.startsWith('root_') ? NOT_CLASSIFIED : 'Unassigned';
      const historyPill = (value) => pill(kind === 'status_auto' ? 'status' : kind, value, emptyLabel);
      if (kind === 'status_auto') {
        // The Status Rules moved the call after a change of its fields.
        item.classList.add('is-automatic');
        text.append('The status followed the Status Rules ');
        if (entry.old_value) text.append('from ', historyPill(entry.old_value), ' ');
        text.append('to ', historyPill(entry.new_value), ' after a change by ', who);
      } else if (kind.startsWith('field:')) {
        const field = state.fields.find((item) => item.key === kind.slice(6));
        const fieldPill = (value) => {
          const element = node('span', value || 'empty', `nq-pill${value ? '' : ' is-empty'}`);
          if (field) paintPill(element, field.type === 'yes_no' ? YES_NO_COLORS[value] || '' : optionColorOf(field, value));
          return element;
        };
        text.append(who, ` changed ${historyLabel(kind)} `);
        if (entry.old_value) text.append('from ', fieldPill(entry.old_value), ' ');
        text.append('to ', fieldPill(entry.new_value));
      } else {
        text.append(who, ` changed ${HISTORY_LABELS[kind] || kind} `);
        if (entry.old_value) text.append('from ', historyPill(entry.old_value), ' ');
        text.append('to ', historyPill(entry.new_value));
      }
    }
    const time = node('time', relativeTime(entry.changed_at));
    time.title = exactTime(entry.changed_at);
    text.append(' · ', time);
    item.append(text);
    // Admins and super-admins can delete single history entries.
    if (state.user.can_moderate && entry.id) {
      const remove = node('button', '×', 'nq-history-delete');
      remove.type = 'button';
      remove.title = 'Delete this history entry';
      remove.setAttribute('aria-label', 'Delete this history entry');
      remove.addEventListener('click', () => deleteHistory(
        `/api/non-qualified-calls/history/${entry.id}`, {method: 'DELETE'}, 'Delete this history entry? It cannot be recovered.',
      ));
      item.append(remove);
    }
    return item;
  };
  const confirmDelete = async (message) => (typeof window.showConfirmDialog === 'function'
    ? window.showConfirmDialog(message, {title: 'Delete history', confirmLabel: 'Delete'}) : window.confirm(message));
  const deleteHistory = async (url, init, message) => {
    if (!await confirmDelete(message)) return false;
    try {
      const result = await api(url, init);
      toast(`${number(result.deleted)} history entries deleted.`);
      if (state.detail) await openDetail(state.detail.call.call_key, {keepTab: true});
      loadCalls({quiet: true});
      return true;
    } catch (error) {
      toast(error.message, 'error');
      return false;
    }
  };
  const timelineComment = (comment) => {
    const item = node('li', undefined, `nq-event nq-event-comment${comment.deleted_at ? ' is-deleted' : ''}`);
    item.append(avatar(comment.created_by));
    const bubble = node('div', undefined, 'nq-comment');
    const head = node('header');
    const time = node('time', relativeTime(comment.created_at));
    time.title = exactTime(comment.created_at);
    head.append(node('strong', comment.created_by), time);
    if (comment.edited_at && !comment.deleted_at) {
      const edited = node('span', 'edited', 'nq-edited');
      edited.title = `Edited by ${comment.edited_by} · ${exactTime(comment.edited_at)}`;
      head.append(edited);
    }
    bubble.append(head);
    if (comment.deleted_at) {
      bubble.append(node('p', `Comment deleted by ${comment.deleted_by} · ${exactTime(comment.deleted_at)}`, 'nq-muted'));
    } else {
      const body = node('p', comment.body, 'nq-comment-body');
      bubble.append(body);
      if (canChangeComment(comment)) {
        const actions = node('div', undefined, 'nq-comment-actions');
        const edit = node('button', 'Edit', 'nq-link-action');
        const remove = node('button', 'Delete', 'nq-link-action is-danger');
        edit.type = remove.type = 'button';
        edit.addEventListener('click', () => editComment(comment, bubble, body, actions));
        remove.addEventListener('click', () => deleteComment(comment));
        actions.append(edit, remove);
        head.append(actions);
      }
    }
    item.append(bubble);
    return item;
  };
  const editComment = (comment, bubble, body, actions) => {
    actions.hidden = true;
    const editor = node('form', undefined, 'nq-comment-editor');
    const area = node('textarea');
    area.value = comment.body;
    area.rows = Math.min(10, Math.max(3, comment.body.split('\n').length + 1));
    area.maxLength = 5000;
    const save = node('button', 'Save', 'nq-primary-action');
    const cancel = node('button', 'Cancel', 'nq-link-action');
    save.type = 'submit';
    cancel.type = 'button';
    const buttons = node('div', undefined, 'nq-composer-actions');
    buttons.append(cancel, save);
    editor.append(area, buttons);
    body.replaceWith(editor);
    area.focus();
    cancel.addEventListener('click', () => { editor.replaceWith(body); actions.hidden = false; });
    editor.addEventListener('submit', async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        await api(`/api/non-qualified-calls/comments/${comment.id}`, {method: 'PATCH', body: JSON.stringify({body: area.value})});
        toast('Comment updated.');
        await openDetail(commentCallKey(), {keepTab: true});
        loadCalls({quiet: true});
      } catch (error) {
        toast(error.message, 'error');
        save.disabled = false;
      }
    });
  };
  const commentCallKey = () => state.detail?.call.call_key;
  const deleteComment = async (comment) => {
    const accepted = typeof window.showConfirmDialog === 'function'
      ? await window.showConfirmDialog('Delete this comment? It stays in the call history with its author and time.', {title: 'Delete comment', confirmLabel: 'Delete'})
      : window.confirm('Delete this comment?');
    if (!accepted) return;
    try {
      await api(`/api/non-qualified-calls/comments/${comment.id}`, {method: 'DELETE'});
      toast('Comment deleted.');
      await openDetail(commentCallKey(), {keepTab: true});
      loadCalls({quiet: true});
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  // The first list field of a phase section (Analysis, Implementation, Planning) tells the phase of the call.
  // The tab that shows a section.
  const tabOf = (sectionKey) => drawerTabs().find((group) => group.sections.some((section) => section.key === sectionKey))
    || {key: 'general', label: 'Activity'};
  const phaseFields = () => PHASE_SECTIONS.map((key) => state.fields.find((field) => field.section === key && field.type === 'list'
    && ['user', 'derived'].includes(field.source))).filter(Boolean);
  const renderTracking = (call) => {
    const host = $('nq-drawer-tracking');
    const field = (kind, label) => {
      const wrapper = node('label', undefined, 'nq-tracking-field');
      wrapper.append(node('span', label));
      wrapper.append(state.user.can_edit ? trackingSelect(kind, call) : pill(kind, call[kind]));
      return wrapper;
    };
    const status = field('status', 'NQ Call Status');
    status.querySelector('span').append(' ', statusModeBadge(call));
    const updated = node('p', call.updated_by
      ? `Last follow-up by ${call.updated_by} · ${exactTime(call.updated_at)}` : 'Not followed up yet.', 'nq-tracking-note');
    const rootField = node('div', undefined, 'nq-tracking-field nq-tracking-root');
    const domain = call.root_domain ? node('span', call.root_domain, 'nq-domain-tag') : null;
    if (domain) domain.style.setProperty('--nq-section', domainColor(call.root_domain) || '#7b8790');
    const title = node('span', 'Root Category · Root Cause');
    if (domain) title.append(' ', domain);
    rootField.append(title, rootCauseControl(call));
    // The phases of the call, each in the colour of its section; a click opens its tab. The first one, RCA
    // Identification, is done once a root category or cause is selected.
    const phases = node('div', undefined, 'nq-phase-strip');
    const phaseStep = (sectionKey, name, value, color, title, empty = 'Not started') => {
      const section = sectionOf(sectionKey);
      if (phases.childElementCount) phases.append(node('span', '›', 'nq-phase-arrow'));
      const step = node('button', undefined, `nq-phase-step${value ? '' : ' is-empty'}`);
      step.type = 'button';
      step.style.setProperty('--nq-section', section.color);
      const valuePill = node('span', value || empty, 'nq-pill');
      paintPill(valuePill, color);
      if (!value) valuePill.classList.add('is-empty');
      step.append(node('span', name, 'nq-phase-name'), valuePill);
      step.title = `${title}: ${value || empty} — open ${tabOf(sectionKey).label}`;
      step.addEventListener('click', () => selectTab(tabOf(sectionKey).key));
      phases.append(step);
    };
    if (state.sections.some((section) => section.key === 'rca')) {
      const identified = call.root_category || call.root_cause;
      const recommended = !identified && recommendationOf(call);
      phaseStep('rca', 'RCA Identification', identified, optionColor('root_category', call.root_category) || optionColor('root_cause', call.root_cause),
        'RCA Identification', recommended ? 'Recommended' : 'Not started');
    }
    phaseFields().forEach((phase) => {
      const value = String(call.values?.[phase.key] || '');
      phaseStep(phase.section, sectionOf(phase.section).label, value, optionColorOf(phase, value), phase.label);
    });
    host.replaceChildren(status, field('team', 'Team'), field('assignee', 'Assignee'), rootField,
      ...(phases.childElementCount ? [phases] : []), updated);
  };
  const DETAIL_FIELDS = [
    ['Service', 'service_label'], ['Result', 'result'], ['Operator', 'operator'], ['Vendor', 'vendor'], ['Campaign', 'campaign'],
    ['NR Mode', 'nr_mode'], ['Region', 'region'], ['City', 'city'], ['Technology', 'technology'], ['Test Name', 'test_name'],
    ['Session Type', 'session_type'], ['Direction', 'direction'], ['Start Time', 'start_time'], ['End Time', 'end_time'],
    ['Failure Phase', 'failure_phase'],
    ['Failure Technology', 'failure_technology'], ['Failure Classification', 'failure_classification'],
    ['Failure Category', 'failure_category'], ['Failure Subcategory', 'failure_subcategory'],
    ['Failure Comment', 'failure_comment'], ['Cell ID', 'cell_id'], ['Root Domain', 'root_domain'], ['Root Category', 'root_category'],
    ['Root Cause', 'root_cause'], ['JOIN_ID', 'join_id'], ['CDR', 'dataset_name'],
  ];
  const renderFields = () => {
    const filter = $('nq-field-search').value.trim().toLowerCase();
    const rows = (state.detail?.fields || []).filter(([name, value]) => !filter
      || name.toLowerCase().includes(filter) || String(value).toLowerCase().includes(filter));
    $('nq-fields').replaceChildren(...rows.map(([name, value]) => {
      const row = node('tr');
      row.append(node('th', name), node('td', value));
      return row;
    }));
    if (!rows.length) {
      const row = node('tr');
      const cell = node('td', state.detail?.fields?.length ? 'No field matches.' : 'The CDR row is no longer available.', 'nq-muted');
      cell.colSpan = 2;
      row.append(cell);
      $('nq-fields').append(row);
    }
  };
  // A field entered by the analysts, edited in its section and saved with the version of the call.
  const fieldInput = (field, value) => {
    let control;
    if (field.type === 'list' || field.type === 'yes_no') {
      // A list is chosen in the coloured picker; its value travels in a hidden input, saved with the others.
      const wrapper = node('div', undefined, 'nq-choice-field');
      const input = node('input');
      input.type = 'hidden';
      input.value = value;
      input.dataset.fieldKey = field.key;
      input.dataset.original = value;
      const changed = (chosen) => {
        input.value = chosen;
        input.dispatchEvent(new Event('change', {bubbles: true}));
      };
      const picker = choiceControl({items: fieldChoices(field, value), value, label: field.label, onChange: changed});
      picker.disabled = !state.user.can_edit;
      wrapper.append(picker, input);
      wrapper.setValue = (chosen) => { picker.setValue(chosen); changed(chosen); };
      return wrapper;
    } else if (field.type === 'long_text') {
      control = node('textarea');
      control.rows = 8;
      control.maxLength = 20000;
      control.value = value;
    } else {
      control = node('input');
      control.type = field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text';
      if (field.type === 'number') control.step = 'any';
      if (field.type === 'text') control.maxLength = 300;
      control.value = value;
    }
    control.dataset.fieldKey = field.key;
    control.dataset.original = value;
    control.disabled = !state.user.can_edit;
    control.setAttribute('aria-label', field.label);
    return control;
  };
  // A field from the CDR, the RCA script, the follow-up or derived from the call: shown, never edited.
  const readonlyValue = (field, value) => {
    const box = node('div', undefined, 'nq-readonly-value');
    const text = value === null || value === undefined ? '' : String(value);
    if (['list', 'yes_no'].includes(field.type) && text) {
      const element = node('span', text, 'nq-pill');
      paintPill(element, field.type === 'yes_no' ? YES_NO_COLORS[text] || '' : optionColorOf(field, text));
      box.append(element);
    } else {
      box.append(node('span', text || '—', text ? '' : 'nq-muted'));
    }
    return box;
  };
  const changedFields = () => {
    const changes = {};
    drawer.querySelectorAll('[data-field-key]').forEach((control) => {
      if (control.value !== control.dataset.original) changes[control.dataset.fieldKey] = control.value;
    });
    return changes;
  };
  // Every section tells how many of the fields of the call are still unsaved.
  const syncUnsaved = () => {
    const count = Object.keys(changedFields()).length;
    drawer.querySelectorAll('.nq-section-form .nq-composer-note').forEach((note) => {
      note.textContent = count ? `${count} unsaved change${count === 1 ? '' : 's'} (Save keeps those of every section)` : '';
    });
    drawer.classList.toggle('has-unsaved', count > 0);
  };
  const fieldBlock = (field, call) => {
    const editable = field.source === 'user';
    const wrapper = node(editable ? 'label' : 'div', undefined, `nq-analysis-field is-${field.type}${editable ? '' : ' is-readonly'}`);
    const title = node('span', field.label, 'nq-field-title');
    if (!editable) title.append(node('small', SOURCE_TAGS[field.source] || field.source, `nq-source-tag is-${field.source}`));
    if (field.required_to_close) title.append(node('small', 'required to close', 'nq-required-tag'));
    if (field.description) wrapper.title = field.description;
    wrapper.append(title);
    if (!editable) {
      wrapper.append(readonlyValue(field, call.values?.[field.key]));
      return wrapper;
    }
    const value = call.fields?.[field.key] || '';
    const control = fieldInput(field, value);
    wrapper.append(control);
    // A value of the CDR proposed for the empty field (a list only proposes one of its values).
    let proposal = call.proposals?.[field.key];
    if (proposal && field.type === 'list') proposal = field.options.find((option) => option.name.toLowerCase() === proposal.toLowerCase())?.name;
    if (proposal && state.user.can_edit && !value) {
      const use = node('button', `Use the CDR value: ${proposal}`, 'nq-proposal');
      use.type = 'button';
      use.title = `Fill ${field.label} with the ${field.suggest_from} of the CDR; Save keeps it`;
      use.addEventListener('click', (event) => {
        event.preventDefault();
        if (control.setValue) control.setValue(proposal);
        else {
          control.value = proposal;
          control.dispatchEvent(new Event('change', {bubbles: true}));
        }
        use.remove();
      });
      wrapper.append(use);
    }
    return wrapper;
  };
  const saveFields = async (call, button) => {
    const changes = changedFields();
    if (!Object.keys(changes).length) { toast('Nothing to save.'); return; }
    button.disabled = true;
    try {
      const updated = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
        method: 'PATCH', body: JSON.stringify({changes: {fields: changes}, version: call.version}),
      });
      renderDetail(updated);
      toast('Fields saved.');
      loadCalls({quiet: true});
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  };
  // The Root Cause Decision of the RCA section: the selected Root Category and Cause, the recommendation
  // merged from every source, and what each source (RCA script, NetCheck, comments, previous decisions) proposes.
  const rootDecisionCard = (call) => {
    const card = node('section', undefined, 'nq-decision');
    const head = node('header');
    head.append(node('h3', 'Root Cause Decision'), node('p', 'The Root Category and Root Cause of the call, chosen independently from the catalog. Accept the recommendation, use what one source proposes or choose any other value.', 'form-note'));
    const current = node('div', undefined, 'nq-decision-current');
    const pickers = node('div', undefined, 'nq-root-cell');
    if (state.user.can_edit) pickers.append(rootPickerButton('root_category', call), rootPickerButton('root_cause', call));
    else pickers.append(pill('root_category', call.root_category, NOT_CLASSIFIED), pill('root_cause', call.root_cause, NO_CAUSE));
    current.append(node('span', 'Selected', 'nq-decision-label'), pickers);
    if (call.root_domain) {
      const domain = node('span', call.root_domain, 'nq-domain-tag');
      domain.style.setProperty('--nq-section', domainColor(call.root_domain) || '#7b8790');
      domain.title = 'The domain of the root category (else of the root cause)';
      current.append(domain);
    }
    card.append(head, current);
    const recommendation = recommendationOf(call);
    if (recommendation) {
      const chosen = (recommendation.category || '') === (call.root_category || '') && (recommendation.cause || '') === (call.root_cause || '');
      const banner = node('div', undefined, `nq-recommendation is-${recommendation.confidence}${chosen ? ' is-chosen' : ''}`);
      const body = node('div');
      const values = node('p');
      values.append(node('strong', 'Recommended: '), recommendation.category ? pill('root_category', recommendation.category) : '',
        ' ', recommendation.cause ? pill('root_cause', recommendation.cause) : '');
      body.append(values, node('span', `${CONFIDENCE_LABELS[recommendation.confidence] || ''} · ${sourceNames(recommendation.sources)}`, 'nq-muted'));
      banner.append(node('span', '★', 'nq-recommendation-icon'), body);
      if (chosen) banner.append(node('span', 'Selected', 'nq-recommendation-state'));
      else if (state.user.can_edit) {
        const accept = node('button', 'Accept', 'nq-primary-action');
        accept.type = 'button';
        accept.addEventListener('click', () => patchCall(call, {root_category: recommendation.category, root_cause: recommendation.cause},
          accept, 'Recommendation accepted.'));
        banner.append(accept);
      }
      card.append(banner);
    }
    const sources = call.rca_recommendation?.sources || [];
    const cards = node('div', undefined, 'nq-source-cards');
    sources.forEach((source) => {
      const item = node('article', undefined, `nq-source-card is-${source.source}`);
      const title = node('header');
      title.append(node('strong', source.label || state.rcaSources[source.source] || source.source));
      if (source.count) title.append(node('span', `${number(source.count)} earlier calls`, 'nq-muted'));
      item.append(title);
      if (source.raw_category || source.raw_cause) {
        item.append(node('p', [source.raw_category, source.raw_cause].filter(Boolean).join(' → '), 'nq-source-raw'));
      }
      const mapped = node('p', undefined, 'nq-source-mapped');
      if (source.category || source.cause) {
        if (source.category) mapped.append(pill('root_category', source.category));
        if (source.cause) mapped.append(' ', pill('root_cause', source.cause));
      } else {
        mapped.append(node('span', source.domain ? `${source.domain} (no category or cause matches)` : 'Not in the catalog yet: add keywords to map it', 'nq-muted'));
      }
      item.append(mapped);
      const changes = {};
      if (source.category) changes.root_category = source.category;
      if (source.cause) changes.root_cause = source.cause;
      const same = Object.entries(changes).every(([key, value]) => (call[key] || '') === value);
      if (state.user.can_edit && Object.keys(changes).length && !same) {
        const use = node('button', 'Use', 'nq-secondary-action');
        use.type = 'button';
        use.title = `Set ${Object.values(changes).join(' · ')}`;
        use.addEventListener('click', () => patchCall(call, changes, use, `${source.label} applied.`));
        item.append(use);
      }
      cards.append(item);
    });
    if (!sources.length) cards.append(node('p', 'No RCA source proposes a root cause for this call yet: import the RCA script results or choose the values by hand.', 'form-note'));
    card.append(node('h4', 'What each source proposes'), cards);
    // Other columns of the RCA script file.
    const extras = Object.entries(call.rca || {}).filter(([key, value]) => key.startsWith('extra:') && value);
    if (extras.length) {
      const list = node('dl', undefined, 'nq-detail-grid nq-rca-extra');
      extras.forEach(([key, value]) => list.append(node('dt', key.slice(6)), node('dd', String(value))));
      card.append(node('h4', 'Other RCA script columns'), list);
    }
    return card;
  };
  // The fields of every section, each one in its tab; the tabs count the fields filled in.
  // The fields of every tab; a tab of several sections (Implementation & Planning) shows each one in its own subpanel.
  // The tabs count the fields filled in.
  const renderSections = (detail) => {
    const call = detail.call;
    drawerTabs().forEach((group) => {
      const host = group.key === 'general' ? $('nq-general-fields')
        : drawer.querySelector(`[data-nq-panel="${CSS.escape(group.key)}"] .nq-section-fields`);
      if (!host) return;
      const ofSection = (key) => state.fields.filter((field) => field.section === key && field.source !== 'tracking');
      const fields = group.sections.flatMap((section) => ofSection(section.key));
      const editable = fields.filter((field) => field.source === 'user');
      const parts = group.key === 'rca' ? [rootDecisionCard(call)] : [];
      if (fields.length) {
        const form = node('form', undefined, 'nq-analysis-form nq-section-form');
        if (group.key === 'rca') form.append(node('h4', 'Values of the RCA sources'));
        group.sections.forEach((section) => {
          const sectionFields = ofSection(section.key);
          if (!sectionFields.length) return;
          const grid = node('div', undefined, 'nq-analysis-grid');
          grid.append(...sectionFields.map((field) => fieldBlock(field, call)));
          if (group.sections.length === 1) { form.append(grid); return; }
          const subpanel = node('section', undefined, 'nq-subpanel');
          subpanel.style.setProperty('--nq-section', section.color);
          subpanel.append(node('h4', section.label), grid);
          form.append(subpanel);
        });
        if (editable.length && state.user.can_edit) {
          const actions = node('div', undefined, 'nq-composer-actions');
          const save = node('button', `Save ${group.key === 'general' ? 'Fields' : group.label}`, 'nq-primary-action');
          save.type = 'submit';
          actions.append(node('span', '', 'nq-composer-note'), save);
          form.append(actions);
          form.onsubmit = (event) => { event.preventDefault(); saveFields(call, save); };
        }
        parts.push(form);
      } else if (!['general', 'rca'].includes(group.key)) {
        parts.push(node('p', state.user.can_edit ? 'No fields in this section yet: add them in Analysis Center › Fields & Sections.'
          : 'No fields in this section.', 'form-note'));
      }
      host.replaceChildren(...parts);
      const badge = drawer.querySelector(`[data-nq-tab="${CSS.escape(group.key)}"] .nq-tab-badge`);
      if (!badge) return;
      let text = '';
      let title = '';
      let complete = false;
      if (group.key === 'rca') {
        complete = Boolean(call.root_category || call.root_cause);
        text = complete ? '✓' : recommendationOf(call) ? '★' : '';
        title = complete ? 'A root category or cause is selected' : 'A recommended root category and cause wait to be accepted';
      } else if (editable.length) {
        const filled = editable.filter((field) => call.fields?.[field.key]).length;
        text = `${filled}/${editable.length}`;
        title = `${filled} of the ${editable.length} fields the analysts fill in here have a value`;
        complete = filled === editable.length;
      }
      badge.textContent = text;
      badge.title = title;
      badge.hidden = !text;
      badge.classList.toggle('is-complete', complete);
    });
    syncUnsaved();
  };
  const renderSamples = (detail) => {
    const samples = detail.samples || [];
    $('nq-samples').hidden = !samples.length;
    $('nq-sample-list').replaceChildren(...samples.map((sample) => {
      const item = node('li');
      const button = node('button', undefined, 'nq-sample');
      button.type = 'button';
      button.title = 'Open this sample to follow it up';
      const head = node('span', undefined, 'nq-sample-head');
      head.append(node('strong', cdrTime(sample.start_time)), node('span', sample.result || '—', `nq-result ${resultClass(sample.result)}`));
      const failure = node('span', [sample.failure_classification, sample.failure_category].filter(Boolean).join(' · ') || 'Not classified',
        'nq-sample-failure');
      const tracking = node('span', undefined, 'nq-sample-tracking');
      tracking.append(pill('status', sample.status), node('span', rootLabel(sample.root_category, sample.root_cause), 'nq-muted'),
        node('span', `${number(sample.comment_count)} comments`, 'nq-muted'));
      button.append(head, failure, tracking);
      button.addEventListener('click', () => openDetail(sample.call_key, {keepTab: false}));
      item.append(button);
      return item;
    }));
  };
  const renderVersions = (detail) => {
    const versions = detail.versions || [];
    $('nq-versions').hidden = versions.length < 2;
    $('nq-version-list').replaceChildren(...versions.map((version) => {
      const item = node('li', undefined, `nq-version-item${version.dataset_id === Number(detail.call.dataset_id) ? ' is-shown' : ''}`);
      item.append(node('span', version.stage, `nq-stage nq-stage-${version.stage.toLowerCase()}`),
        node('strong', version.name || `CDR ${version.dataset_id}`));
      const facts = [version.data_date ? `Calls until ${cdrTime(version.data_date)}` : '',
        version.non_qualified ? [version.result, version.failure_classification].filter(Boolean).join(' · ') : 'Completed'];
      item.append(node('span', facts.filter(Boolean).join(' · '), 'nq-muted'));
      if (version.latest) item.append(node('span', 'Latest', 'nq-version is-latest'));
      if (version.dataset_id === Number(detail.call.dataset_id)) item.append(node('span', 'Shown', 'nq-version is-shown'));
      return item;
    }));
  };
  function renderDetail(detail) {
    state.detail = detail;
    const call = detail.call;
    const eyebrow = [node('span', call.service_label, `nq-service nq-service-${call.service}`), ' ',
      node('span', call.result || '—', `nq-result ${resultClass(call.result)}`)];
    if (call.parent_key) {
      // A Speech sample: back to its call.
      const back = node('button', '‹ Back to the call', 'nq-link-action nq-back-to-call');
      back.type = 'button';
      back.addEventListener('click', () => { openDetail(call.parent_key, {keepTab: false}); });
      eyebrow.push(' ', node('span', `Sample ${call.sample_id || ''}`.trim(), 'nq-samples-badge'), ' ', back);
    }
    const badge = versionBadge(call);
    if (badge) eyebrow.push(' ', badge);
    $('nq-drawer-eyebrow').replaceChildren(...eyebrow);
    $('nq-drawer-title').textContent = [call.operator, call.campaign && campaignLabel(call.campaign)].filter(Boolean).join(' · ') || 'Call details';
    $('nq-drawer-meta').textContent = [cdrTime(call.start_time), call.city, call.technology, call.test_name].filter((value) => value && value !== '—').join(' · ');
    renderTracking(call);
    renderSections(detail);
    renderSamples(detail);
    renderVersions(detail);
    const events = [
      ...detail.comments.map((comment) => ({time: comment.created_at, item: timelineComment(comment)})),
      ...detail.history.map((entry) => ({time: entry.changed_at, item: timelineChange(entry)})),
    ].sort((a, b) => String(a.time).localeCompare(String(b.time)));
    const timeline = $('nq-timeline');
    timeline.replaceChildren(...events.map((event) => event.item));
    $('nq-history-actions').hidden = !(state.user.can_moderate && detail.history.length);
    if (!events.length) timeline.append(node('li', state.user.can_edit ? 'No activity yet. Start the follow-up with a comment.' : 'No activity yet.', 'nq-empty-timeline'));
    const grid = $('nq-detail-grid');
    grid.replaceChildren();
    DETAIL_FIELDS.forEach(([label, key]) => {
      const value = key.endsWith('_time') ? cdrTime(call[key]) : key === 'campaign' && call[key] ? campaignLabel(call[key]) : call[key];
      if (!value || value === '—') return;
      grid.append(node('dt', label), node('dd', value));
    });
    if (call.latitude != null && call.longitude != null) {
      const link = node('a', `${Number(call.latitude).toFixed(5)}, ${Number(call.longitude).toFixed(5)}`);
      link.href = `https://www.openstreetmap.org/?mlat=${call.latitude}&mlon=${call.longitude}#map=16/${call.latitude}/${call.longitude}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      const value = node('dd');
      value.append(link);
      grid.append(node('dt', 'Location'), value);
    }
    renderFields();
  }
  async function openDetail(callKey, {focusComposer = false, keepTab = false} = {}) {
    if (!callKey) return;
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    backdrop.hidden = false;
    if (!keepTab) selectTab('general');
    if (state.detail?.call.call_key !== callKey) {
      $('nq-timeline').replaceChildren(node('li', 'Loading…', 'nq-empty-timeline'));
      $('nq-comment-body').value = '';
    }
    try {
      const body = drawer.querySelector('.nq-drawer-body');
      const scroll = body.scrollTop;
      renderDetail(await api(`/api/non-qualified-calls/calls/${encodeURIComponent(callKey)}`));
      // The newest activity is at the bottom, next to the comment box.
      body.scrollTop = keepTab ? scroll : body.scrollHeight;
      if (focusComposer && state.user.can_edit) $('nq-comment-body').focus({preventScroll: true});
    } catch (error) {
      toast(error.message, 'error');
      if (error.status === 404) closeDrawer();
    }
  }

  // -- statuses and teams dialog --------------------------------------------------
  const optionsDialog = $('nq-options-dialog');
  const optionRow = (kind, item = {name: '', color: kind === 'statuses' ? '#6a63c9' : '#0f6f7d', closed: false}) => {
    const row = node('li', undefined, 'nq-option-row');
    row.dataset.previous = item.name || '';
    const color = node('input');
    color.type = 'color';
    color.value = item.color;
    color.setAttribute('aria-label', 'Colour');
    const name = node('input');
    name.type = 'text';
    name.value = item.name;
    name.maxLength = 60;
    name.placeholder = kind === 'statuses' ? 'Status name' : 'Team name';
    name.setAttribute('aria-label', name.placeholder);
    row.append(color, name);
    if (kind === 'statuses') {
      const closed = node('label', undefined, 'nq-option-closed');
      const box = node('input');
      box.type = 'checkbox';
      box.checked = Boolean(item.closed);
      closed.append(box, ' Closed');
      closed.title = 'Calls with this status count as closed';
      row.append(closed);
    } else {
      // The members of the team are chosen in their own dialog and saved with the statuses and teams.
      row.members = [...(item.members || [])];
      const members = node('button', membersLabel(row.members), 'nq-members-action');
      members.type = 'button';
      members.title = 'Choose the users of this team';
      members.addEventListener('click', () => openMembers(row));
      row.append(members);
    }
    const move = (offset) => {
      const sibling = offset < 0 ? row.previousElementSibling : row.nextElementSibling;
      if (sibling) (offset < 0 ? sibling.before(row) : sibling.after(row));
    };
    [['↑', 'Move up', () => move(-1)], ['↓', 'Move down', () => move(1)], ['×', 'Remove', () => row.remove()]].forEach(([label, title, action]) => {
      const button = node('button', label, 'nq-icon-action');
      button.type = 'button';
      button.title = title;
      button.setAttribute('aria-label', title);
      button.addEventListener('click', action);
      row.append(button);
    });
    return row;
  };
  const membersLabel = (members) => (members.length ? `${members.length} member${members.length === 1 ? '' : 's'}` : 'Everyone');
  const membersDialog = $('nq-members-dialog');
  let membersRow = null;
  const openMembers = (row) => {
    membersRow = row;
    const team = row.querySelector('input[type="text"]').value.trim() || 'the new team';
    $('nq-members-title').textContent = `Members of ${team}`;
    const chosen = new Set(row.members.map((member) => member.toLocaleLowerCase()));
    const users = [...new Set([...state.users, ...row.members])].sort((left, right) => left.localeCompare(right));
    $('nq-members-list').replaceChildren(...users.map((user) => {
      const item = node('li');
      const label = node('label', undefined, 'nq-members-option');
      const box = node('input');
      box.type = 'checkbox';
      box.value = user;
      box.checked = chosen.has(user.toLocaleLowerCase());
      label.append(box, node('span', user));
      item.append(label);
      return item;
    }));
    if (!users.length) $('nq-members-list').append(node('li', 'No users have access to this workspace.', 'form-note'));
    $('nq-members-search').value = '';
    membersDialog.showModal();
    $('nq-members-search').focus();
  };
  const openOptions = () => {
    ['statuses', 'teams'].forEach((kind) => {
      optionsDialog.querySelector(`[data-nq-options="${kind}"]`).replaceChildren(...state.options[kind].map((item) => optionRow(kind, item)));
    });
    $('nq-options-error').style.color = '';
    $('nq-options-error').textContent = '';
    optionsDialog.showModal();
  };
  const collectOptions = (kind) => [...optionsDialog.querySelectorAll(`[data-nq-options="${kind}"] .nq-option-row`)].map((row) => {
    const [color, name] = row.querySelectorAll('input');
    return {name: name.value.trim(), color: color.value, previous: row.dataset.previous,
      closed: Boolean(row.querySelector('.nq-option-closed input')?.checked),
      ...(kind === 'teams' ? {members: row.members || []} : {})};
  });

  // -- events -------------------------------------------------------------------
  root.addEventListener('change', (event) => {
    if (event.target.matches('[data-nq-filter], [data-nq-flag]')) scheduleLoad();
  });
  $('nq-search').addEventListener('input', debounce(() => { state.page = 1; loadCalls(); }, 400));
  root.querySelectorAll('[data-nq-typed-filter]').forEach((input) => input.addEventListener('input', debounce(() => { state.page = 1; loadCalls(); }, 400)));
  // Join ID sits in the title bar of its panel, which folds the panel: using it never folds it.
  root.querySelectorAll('[data-nq-join-search]').forEach((search) => {
    search.addEventListener('click', (event) => {
      event.preventDefault();
      search.querySelector('input')?.focus();
    });
    search.addEventListener('keyup', (event) => { if (event.key === ' ' || event.key === 'Enter') event.preventDefault(); });
  });
  $('nq-reset').addEventListener('click', () => {
    filterSelects().forEach((select) => { [...select.options].forEach((option) => { option.selected = false; }); select.dispatchEvent(new Event('change')); });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { box.checked = false; });
    root.querySelectorAll('[data-nq-typed-filter]').forEach((input) => { input.value = ''; });
    state.extraFilters = {};
    $('nq-search').value = '';
    scheduleLoad();
  });
  // Reindex: the calls of every CDR are indexed again in the background (their follow-up is kept); the page
  // reloads them once it ends.
  $('nq-refresh').addEventListener('click', async () => {
    $('nq-refresh').disabled = true;
    try {
      const {sync} = await api('/api/non-qualified-calls/reindex', {method: 'POST'});
      renderSync(sync);
    } catch (error) {
      $('nq-sync').textContent = error.message;
      $('nq-refresh').disabled = false;
    }
  });
  $('nq-page-size').addEventListener('change', (event) => { state.pageSize = Number(event.target.value) || 50; state.page = 1; loadCalls(); });
  // -- scroll position: a reload returns to where the page was, while its panels load ------------
  const SCROLL_STORAGE = `nq-scroll:${window.location.pathname}`;
  const rememberScroll = () => {
    try {
      window.sessionStorage.setItem(SCROLL_STORAGE, String(Math.round(window.scrollY)));
    } catch (_error) {
      // Without session storage a reload opens the page at its top.
    }
  };
  window.addEventListener('pagehide', rememberScroll);
  (() => {
    let target = 0;
    try {
      target = Number(window.sessionStorage.getItem(SCROLL_STORAGE)) || 0;
    } catch (_error) {
      target = 0;
    }
    if (target <= 0 || !('ResizeObserver' in window)) return;
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
    // The panels fill in after the page opens, so the position is applied again as the page grows,
    // until the reader scrolls or the page has settled.
    const observer = new ResizeObserver(() => window.scrollTo({top: target, behavior: 'auto'}));
    const stop = () => {
      observer.disconnect();
      ['wheel', 'touchstart', 'keydown', 'mousedown'].forEach((type) => window.removeEventListener(type, stop));
    };
    ['wheel', 'touchstart', 'keydown', 'mousedown'].forEach((type) => window.addEventListener(type, stop, {passive: true}));
    observer.observe(document.body);
    window.scrollTo({top: target, behavior: 'auto'});
    window.setTimeout(stop, 10000);
  })();
  $('nq-column-order-reset').addEventListener('click', () => {
    saveColumnOrder(defaultColumnOrder());
    applyColumnOrder([]);
    if (state.result) renderRows(state.result);
  });
  $('nq-table').querySelectorAll('[data-sort]').forEach(bindSort);
  $('nq-select-page')?.addEventListener('change', (event) => {
    (state.result?.calls || []).forEach((call) => {
      if (event.target.checked) state.selected.add(call.call_key); else state.selected.delete(call.call_key);
    });
    if (state.result) renderRows(state.result);
    renderBulk();
  });
  $('nq-bulk-clear')?.addEventListener('click', () => {
    state.selected.clear();
    if (state.result) renderRows(state.result);
    renderBulk();
  });
  const confirmBulk = async (message) => (typeof window.showConfirmDialog === 'function'
    ? window.showConfirmDialog(message, {title: 'Change selected calls', confirmLabel: 'Apply'}) : window.confirm(message));
  const bulkChange = async (changes) => {
    try {
      const result = await api('/api/non-qualified-calls/calls/bulk', {
        method: 'POST', body: JSON.stringify({call_keys: [...state.selected], changes}),
      });
      toast(`${number(result.changed)} calls updated.`);
      loadCalls({quiet: true});
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  // Status (or back to the Status Rules), team, assignee, root category and root cause of the selected calls.
  [['nq-bulk-status', 'status'], ['nq-bulk-team', 'team'], ['nq-bulk-assignee', 'assignee'], ['nq-bulk-category', 'root_category'],
    ['nq-bulk-root', 'root_cause']].forEach(([id, kind]) => {
    $(id)?.addEventListener('change', async (event) => {
      const value = event.target.value;
      if (!value) return;
      event.target.value = '';
      const count = number(state.selected.size);
      if (value === AUTO_STATUS) {
        if (!await confirmBulk(`Give the status of the ${count} selected calls back to the Status Rules?`)) return;
        bulkChange({status_mode: 'auto'});
        return;
      }
      const target = value === state.unassigned ? '' : value;
      const empty = kind === 'root_cause' ? NO_CAUSE : kind === 'root_category' ? NOT_CLASSIFIED : 'Unassigned';
      if (!await confirmBulk(`Set ${HISTORY_LABELS[kind]} to “${target || empty}” for ${count} selected calls?`)) return;
      bulkChange({[kind]: target});
    });
  });
  $('nq-bulk-field')?.addEventListener('change', async (event) => {
    const value = event.target.value;
    if (!value) return;
    event.target.value = '';
    const [key, ...rest] = value.split(ROOT_SEPARATOR);
    const target = rest.join(ROOT_SEPARATOR);
    const label = historyLabel(`field:${key}`);
    if (!await confirmBulk(`Set ${label} to “${target || 'empty'}” for ${number(state.selected.size)} selected calls?`)) return;
    bulkChange({fields: {[key]: target}});
  });
  $('nq-history-clear').addEventListener('click', () => {
    const callKey = state.detail?.call.call_key;
    if (!callKey) return;
    deleteHistory('/api/non-qualified-calls/history/clear', {method: 'POST', body: JSON.stringify({call_keys: [callKey]})},
      'Delete the whole history of this call? Its status, team, assignee, root cause and comments stay; the history cannot be recovered.');
  });
  $('nq-bulk-history')?.addEventListener('click', async () => {
    const count = state.selected.size;
    await deleteHistory('/api/non-qualified-calls/history/clear', {method: 'POST', body: JSON.stringify({call_keys: [...state.selected]})},
      `Delete the whole history of the ${number(count)} selected calls? Their follow-up and comments stay; the history cannot be recovered.`);
  });
  $('nq-bulk-suggest')?.addEventListener('click', async () => {
    if (!await confirmBulk(`Give the ${number(state.selected.size)} selected calls without a root category and cause the ones recommended by their RCA sources?`)) return;
    bulkChange({apply_recommendation: true});
  });
  // Executive Summary and Progress Status of the filtered calls, as on the page, in PowerPoint or Word.
  document.querySelectorAll('[data-nq-document-export]').forEach((button) => button.addEventListener('click', async () => {
    const kind = button.dataset.nqDocumentExport;
    const label = kind === 'word' ? 'Word' : 'PowerPoint';
    button.disabled = true;
    globalThis.showLoadingOverlay?.(`Preparing the ${label} document`,
      `Preparing the Non-Qualified Calls ${label} with the Executive Summary, the Progress Status and the Root Cause Analysis of the filtered calls. The document downloads when it is ready.`);
    try {
      const response = await fetch(`/api/non-qualified-calls/export/${kind}`, {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filters: currentFilters(), granularity: $('nq-granularity').value,
          include_suggestions: $('nq-root-suggestions').checked}),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === 'string' ? payload.detail : `The ${label} export failed.`);
      }
      const disposition = response.headers.get('Content-Disposition') || '';
      const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `Non-Qualified Calls.${kind === 'word' ? 'docx' : 'pptx'}`;
      const url = URL.createObjectURL(await response.blob());
      const link = node('a');
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      globalThis.hideLoadingOverlay?.();
      if (typeof globalThis.showInfoDialog === 'function') globalThis.showInfoDialog(error.message, {tone: 'error', title: 'The document could not be generated'});
      else toast(error.message, 'error');
    } finally {
      globalThis.hideLoadingOverlay?.();
      button.disabled = false;
    }
  }));
  $('nq-export').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const label = button.textContent;
    button.textContent = 'Exporting…';
    try {
      const response = await fetch('/api/non-qualified-calls/export', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filters: currentFilters()}),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The export failed.');
      }
      const disposition = response.headers.get('Content-Disposition') || '';
      const name = /filename="([^"]+)"/.exec(disposition)?.[1] || 'non-qualified-calls.xlsx';
      const url = URL.createObjectURL(await response.blob());
      const link = node('a');
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });
  $('nq-drawer-close').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && drawer.classList.contains('is-open') && !document.querySelector('dialog[open]')) closeDrawer();
  });
  drawer.querySelectorAll('[data-nq-tab]').forEach((tab) => tab.addEventListener('click', () => selectTab(tab.dataset.nqTab)));
  ['input', 'change'].forEach((type) => drawer.addEventListener(type, (event) => {
    if (event.target.matches?.('[data-field-key]')) syncUnsaved();
  }));
  $('nq-field-search').addEventListener('input', renderFields);
  const composer = $('nq-composer');
  const composerBody = $('nq-comment-body');
  const postComment = async () => {
    const callKey = state.detail?.call.call_key;
    if (!callKey || !composerBody.value.trim()) return;
    const submit = composer.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api(`/api/non-qualified-calls/calls/${encodeURIComponent(callKey)}/comments`, {
        method: 'POST', body: JSON.stringify({body: composerBody.value}),
      });
      composerBody.value = '';
      $('nq-composer-note').textContent = '';
      await openDetail(callKey, {keepTab: true});
      const body = drawer.querySelector('.nq-drawer-body');
      body.scrollTop = body.scrollHeight;
      loadCalls({quiet: true});
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  };
  composer.addEventListener('submit', (event) => { event.preventDefault(); postComment(); });
  composerBody.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); postComment(); }
  });
  composerBody.addEventListener('input', () => {
    const length = composerBody.value.length;
    $('nq-composer-note').textContent = length > 4500 ? `${5000 - length} characters left` : '';
  });
  if (optionsDialog) {
    $('nq-options-open').addEventListener('click', openOptions);
    $('nq-options-cancel').addEventListener('click', () => optionsDialog.close());
    // Only the defaults, in their order and colours (a value with the same name keeps its calls and team members); the
    // others are removed on Save, which refuses a team still used or a status still set by hand.
    optionsDialog.querySelectorAll('[data-nq-option-defaults]').forEach((button) => {
      button.addEventListener('click', () => {
        const kind = button.dataset.nqOptionDefaults;
        const list = optionsDialog.querySelector(`[data-nq-options="${kind}"]`);
        const rows = [...list.querySelectorAll('.nq-option-row')];
        const nameOf = (row) => row.querySelector('input[type="text"]').value.trim().toLowerCase();
        const defaults = state.defaultOptions?.[kind] || [];
        let added = 0;
        const ordered = defaults.map((item) => {
          const existing = rows.find((row) => nameOf(row) === item.name.toLowerCase());
          if (!existing) {
            added += 1;
            return optionRow(kind, item);
          }
          existing.querySelector('input[type="text"]').value = item.name;
          existing.querySelector('input[type="color"]').value = item.color;
          const closed = existing.querySelector('.nq-option-closed input');
          if (closed) closed.checked = Boolean(item.closed);
          return existing;
        });
        const removed = rows.filter((row) => !ordered.includes(row)).map((row) => row.querySelector('input[type="text"]').value.trim());
        list.replaceChildren(...ordered);
        const label = kind === 'statuses' ? 'statuses' : 'teams';
        $('nq-options-error').style.color = 'var(--nq-muted)';
        $('nq-options-error').textContent = `The default ${label} are back (${added} added`
          + (removed.length ? `, ${removed.join(', ')} removed` : '') + '). Save to apply'
          + (kind === 'statuses' ? '; the automatic calls follow the Status Rules again (Default Rules in Status Rules puts the default rules back).' : '.');
      });
    });
    optionsDialog.querySelectorAll('[data-nq-option-add]').forEach((button) => {
      button.addEventListener('click', () => {
        const kind = button.dataset.nqOptionAdd;
        const row = optionRow(kind);
        optionsDialog.querySelector(`[data-nq-options="${kind}"]`).append(row);
        row.querySelector('input[type="text"]').focus();
      });
    });
    $('nq-members-search').addEventListener('input', () => {
      const query = $('nq-members-search').value.trim().toLocaleLowerCase();
      $('nq-members-list').querySelectorAll('li').forEach((item) => {
        item.hidden = Boolean(query) && !item.textContent.toLocaleLowerCase().includes(query);
      });
    });
    $('nq-members-toggle').addEventListener('click', () => {
      const listed = [...$('nq-members-list').querySelectorAll('li:not([hidden]) input')];
      const select = listed.some((box) => !box.checked);
      listed.forEach((box) => { box.checked = select; });
    });
    $('nq-members-cancel').addEventListener('click', () => membersDialog.close());
    $('nq-members-form').addEventListener('submit', () => {
      if (!membersRow) return;
      membersRow.members = [...$('nq-members-list').querySelectorAll('input:checked')].map((box) => box.value);
      membersRow.querySelector('.nq-members-action').textContent = membersLabel(membersRow.members);
    });
    $('nq-options-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-options-save');
      save.disabled = true;
      try {
        const payload = await api('/api/non-qualified-calls/options', {
          method: 'PUT', body: JSON.stringify({statuses: collectOptions('statuses'), teams: collectOptions('teams')}),
        });
        optionsDialog.close();
        toast('Statuses and teams saved.');
        await loadState();
        if (payload && state.detail) openDetail(state.detail.call.call_key, {keepTab: true});
      } catch (error) {
        $('nq-options-error').style.color = '';
        $('nq-options-error').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
  }
  // -- root causes dialog ----------------------------------------------------------
  const rootDialog = $('nq-root-dialog');
  // The suggestion rule in words, as configured for the workspace.
  const ruleText = (rule) => {
    const names = (fields) => fields.map((field) => state.ruleFields[field] || field).join(', ') || 'no field';
    const steps = [];
    if (rule.domain_fields.length) steps.push(`a domain keyword in ${names(rule.domain_fields)} chooses the domain`);
    if (rule.cause_fields.length) {
      steps.push(`a cause keyword in ${names(rule.cause_fields)} chooses the cause${rule.domain_fields.length
        ? (rule.causes_in_domain ? ', among the causes of that domain (or of every domain when none matched)' : ', among every cause') : ''}`);
    }
    if (rule.comments) steps.push(`when the cause is still unresolved, the comments of the call are read the same way${rule.comment_domain ? ', and can also choose the domain' : ''}`);
    const order = 'Domains and causes are tried from top to bottom, so their order sets the priority.';
    const match = rule.match === 'text' ? 'Keywords match any part of the text' : 'Keywords match whole words or phrases';
    return `How a root cause is suggested: ${steps.map((step, index) => `${index + 1}) ${step}`).join('; ')}. ${order} ${match}, separated by commas and ignoring case and underscores.`;
  };
  const iconButtons = (row, item, onRemove) => {
    const move = (offset) => {
      const sibling = offset < 0 ? item.previousElementSibling : item.nextElementSibling;
      if (sibling) (offset < 0 ? sibling.before(item) : sibling.after(item));
    };
    [['↑', 'Move up', () => move(-1)], ['↓', 'Move down', () => move(1)], ['×', 'Remove', onRemove]].forEach(([label, title, action]) => {
      const button = node('button', label, 'nq-icon-action');
      button.type = 'button';
      button.title = title;
      button.setAttribute('aria-label', title);
      button.addEventListener('click', action);
      row.append(button);
    });
  };
  const textInput = (value, placeholder, className = '') => {
    const input = node('input', undefined, className);
    input.type = 'text';
    input.value = value || '';
    input.placeholder = placeholder;
    input.setAttribute('aria-label', placeholder);
    return input;
  };
  // The domains of the catalog being edited, with the name each one had when the dialog opened.
  const catalogDomains = () => [...$('nq-root-domains').children].map((row) => ({
    name: row.querySelector('.nq-root-name').value.trim(), color: row.querySelector('input[type="color"]').value,
  })).filter((domain) => domain.name);
  // A select of the domains, painted in the colour of the chosen one.
  const domainSelect = (current) => {
    const select = node('select', undefined, 'nq-domain-select nq-pill-select');
    select.setAttribute('aria-label', 'Domain');
    select.dataset.current = current || '';
    const paint = () => paintPill(select, catalogDomains().find((domain) => domain.name === select.value)?.color || '');
    select.addEventListener('change', () => { select.dataset.current = select.value; paint(); });
    select.refresh = () => {
      const names = catalogDomains().map((domain) => domain.name);
      const value = select.dataset.current;
      select.replaceChildren(node('option', 'No domain'), ...names.map((name) => {
        const option = node('option', name);
        option.value = name;
        return option;
      }));
      select.options[0].value = '';
      select.value = names.includes(value) ? value : '';
      paint();
    };
    return select;
  };
  const refreshDomainSelects = () => rootDialog.querySelectorAll('.nq-domain-select').forEach((select) => select.refresh());
  const domainRow = (domain = {name: '', color: '#6a63c9', keywords: []}) => {
    const row = node('li', undefined, 'nq-option-row nq-catalog-row');
    row.dataset.previous = domain.name || '';
    row.dataset.current = domain.name || '';
    const color = node('input');
    color.type = 'color';
    color.value = domain.color || '#6a63c9';
    color.setAttribute('aria-label', 'Colour');
    const name = textInput(domain.name, 'Domain name', 'nq-root-name');
    // Renaming a domain renames it in the categories and causes of the dialog.
    name.addEventListener('change', () => {
      const before = row.dataset.current;
      const after = name.value.trim();
      rootDialog.querySelectorAll('.nq-domain-select').forEach((select) => { if (before && select.dataset.current === before) select.dataset.current = after; });
      row.dataset.current = after;
      refreshDomainSelects();
    });
    color.addEventListener('input', refreshDomainSelects);
    row.append(color, name, textInput((domain.keywords || []).join(', '), 'Keywords', 'nq-root-keywords'));
    iconButtons(row, row, () => { row.remove(); refreshDomainSelects(); countCatalog(); });
    return row;
  };
  const entryRow = (kind, item = {name: '', domain: '', keywords: []}) => {
    const row = node('li', undefined, 'nq-option-row nq-catalog-row');
    row.dataset.previous = item.name || '';
    const select = domainSelect(item.domain);
    row.append(textInput(item.name, kind === 'categories' ? 'Root category name' : 'Root cause name', 'nq-root-name'), select,
      textInput((item.keywords || []).join(', '), 'Keywords', 'nq-root-keywords'));
    iconButtons(row, row, () => { row.remove(); countCatalog(); });
    return row;
  };
  const CATALOG_LISTS = {domains: 'nq-root-domains', categories: 'nq-root-categories', causes: 'nq-root-causes'};
  const CATALOG_ADD = {domains: 'Add Domain', categories: 'Add Root Category', causes: 'Add Root Cause'};
  let catalogTab = 'categories';
  const countCatalog = () => rootDialog.querySelectorAll('[data-nq-catalog-tab]').forEach((tab) => {
    tab.querySelector('small').textContent = `(${$(CATALOG_LISTS[tab.dataset.nqCatalogTab]).children.length})`;
  });
  const selectCatalogTab = (name) => {
    catalogTab = name;
    rootDialog.querySelectorAll('[data-nq-catalog-tab]').forEach((tab) => {
      const active = tab.dataset.nqCatalogTab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    Object.entries(CATALOG_LISTS).forEach(([key, id]) => { $(id).hidden = key !== name; });
    $('nq-root-add').textContent = CATALOG_ADD[name];
    filterCatalog();
  };
  const filterCatalog = () => {
    const query = $('nq-root-search').value.trim().toLowerCase();
    $(CATALOG_LISTS[catalogTab]).querySelectorAll(':scope > li').forEach((row) => {
      const text = [...row.querySelectorAll('input[type="text"], select')].map((control) => control.value).join(' ').toLowerCase();
      row.hidden = Boolean(query) && !text.includes(query);
    });
  };
  const collectCatalogRows = (kind) => [...$(CATALOG_LISTS[kind]).children].map((row) => ({
    name: row.querySelector('.nq-root-name').value.trim(), previous: row.dataset.previous,
    keywords: row.querySelector('.nq-root-keywords').value,
    ...(kind === 'domains' ? {color: row.querySelector('input[type="color"]').value}
      : {domain: row.querySelector('.nq-domain-select').value}),
  }));
  const fillCatalog = (catalog) => {
    $('nq-root-domains').replaceChildren(...catalog.domains.map((domain) => domainRow(domain)));
    $('nq-root-categories').replaceChildren(...catalog.categories.map((item) => entryRow('categories', item)));
    $('nq-root-causes').replaceChildren(...catalog.causes.map((item) => entryRow('causes', item)));
    refreshDomainSelects();
    countCatalog();
  };
  if (rootDialog) {
    $('nq-root-open').addEventListener('click', () => {
      $('nq-root-rule-text').textContent = ruleText(state.rootCauses.rule);
      fillCatalog(state.rootCauses);
      $('nq-root-require').checked = Boolean(state.rootCauses.require_to_close);
      $('nq-root-error').textContent = '';
      $('nq-root-search').value = '';
      selectCatalogTab('categories');
      rootDialog.showModal();
    });
    rootDialog.querySelectorAll('[data-nq-catalog-tab]').forEach((tab) => tab.addEventListener('click', () => selectCatalogTab(tab.dataset.nqCatalogTab)));
    $('nq-root-search').addEventListener('input', filterCatalog);
    $('nq-root-cancel').addEventListener('click', () => rootDialog.close());
    // Adds the default domains, root categories and root causes that are missing; existing ones keep their keywords.
    $('nq-root-defaults').addEventListener('click', () => {
      const defaults = state.rootCauseDefaults || {domains: [], categories: [], causes: []};
      let added = 0;
      Object.entries(CATALOG_LISTS).forEach(([kind, id]) => {
        const list = $(id);
        const names = new Set([...list.querySelectorAll('.nq-root-name')].map((input) => input.value.trim().toLowerCase()));
        (defaults[kind] || []).filter((item) => !names.has(item.name.toLowerCase())).forEach((item) => {
          list.append(kind === 'domains' ? domainRow(item) : entryRow(kind, item));
          added += 1;
        });
      });
      refreshDomainSelects();
      countCatalog();
      filterCatalog();
      $('nq-root-error').style.color = 'var(--nq-muted)';
      $('nq-root-error').textContent = added ? `${added} default values added: review them and Save.` : 'Every default value is already in the catalog.';
    });
    $('nq-root-add').addEventListener('click', () => {
      const row = catalogTab === 'domains' ? domainRow() : entryRow(catalogTab);
      $(CATALOG_LISTS[catalogTab]).append(row);
      if (catalogTab !== 'domains') row.querySelector('.nq-domain-select').refresh();
      countCatalog();
      row.querySelector('.nq-root-name').focus();
    });
    $('nq-root-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-root-save');
      save.disabled = true;
      try {
        await api('/api/non-qualified-calls/root-causes', {
          method: 'PUT', body: JSON.stringify({domains: collectCatalogRows('domains'), categories: collectCatalogRows('categories'),
            causes: collectCatalogRows('causes'), require_to_close: $('nq-root-require').checked}),
        });
        rootDialog.close();
        toast('Root cause catalog saved.');
        await loadState();
        if (state.detail) openDetail(state.detail.call.call_key, {keepTab: true});
      } catch (error) {
        $('nq-root-error').style.color = '';
        $('nq-root-error').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
  }
  // -- fields & sections dialog ---------------------------------------------------------------
  const fieldsDialog = $('nq-fields-dialog');
  let fieldSection = '';
  // The sections as edited in the dialog (name and colour), in their fixed order.
  const editedSections = () => [...$('nq-sections-editor').querySelectorAll('[data-section-key]')].map((row) => ({
    key: row.dataset.sectionKey, label: row.querySelector('input[type="text"]').value.trim() || row.dataset.sectionKey,
    color: row.querySelector('input[type="color"]').value,
  }));
  const editedSection = (key) => editedSections().find((section) => section.key === key) || sectionOf(key);
  const fieldValueRow = (option = {name: '', color: '', keywords: []}, withKeywords = false) => {
    const row = node('li', undefined, 'nq-option-row nq-field-value');
    row.dataset.previous = option.name || '';
    const color = node('input');
    color.type = 'color';
    color.value = /^#[0-9a-f]{6}$/i.test(option.color || '') ? option.color : '#b8c0c6';
    color.dataset.chosen = option.color ? '1' : '';
    color.title = 'Colour of the value';
    color.addEventListener('input', () => { color.dataset.chosen = '1'; });
    row.append(color, textInput(option.name, 'Value', 'nq-root-name'));
    if (withKeywords) {
      const keywords = textInput((option.keywords || []).join(', '), 'Keywords found in the call values', 'nq-root-keywords');
      keywords.title = 'The call gets this value when one of these keywords is in the call values the field reads ("a+b" needs both)';
      row.append(keywords);
    }
    iconButtons(row, row, () => row.remove());
    return row;
  };
  // Moves a field past the next visible one, so a filtered list moves as it is shown.
  const moveVisible = (item, offset) => {
    let sibling = offset < 0 ? item.previousElementSibling : item.nextElementSibling;
    while (sibling && sibling.hidden) sibling = offset < 0 ? sibling.previousElementSibling : sibling.nextElementSibling;
    if (sibling) (offset < 0 ? sibling.before(item) : sibling.after(item));
  };
  const selectOf = (className, label, entries, value) => {
    const select = node('select', undefined, className);
    select.setAttribute('aria-label', label);
    select.append(...entries.map(([key, text]) => {
      const option = node('option', text);
      option.value = key;
      return option;
    }));
    select.value = value;
    return select;
  };
  const flagToggle = (name, label, checked, title) => {
    const wrapper = node('label', undefined, 'nq-toggle nq-flag');
    const box = node('input');
    box.type = 'checkbox';
    box.dataset.flag = name;
    box.checked = Boolean(checked);
    wrapper.title = title;
    wrapper.append(box, ` ${label}`);
    return wrapper;
  };
  // Where a field of each source reads its value: call fields, CDR columns or RCA script columns.
  const refChoices = (source) => (source === 'rca' ? Object.entries(state.rcaRefs)
    : source === 'cdr' ? [...state.callFields.map((name) => [name, name]), ...state.cdrColumns.map((name) => [`column:${name}`, `CDR column ${name}`])]
      : source === 'derived' ? state.callFields.map((name) => [name, name]) : []);
  const fieldDefinition = (field = {key: '', label: '', type: 'list', source: 'user', source_ref: '', section: fieldSection || 'analysis',
    options: [], in_table: false, in_export: true, in_summary: false, required_to_close: false, suggest_from: '', description: ''}) => {
    const block = node('li', undefined, 'nq-root-domain nq-field-def');
    block.dataset.key = field.key || '';
    const tracking = field.source === 'tracking';
    const row = node('div', undefined, 'nq-option-row');
    const name = textInput(field.label, 'Field name', 'nq-root-name');
    const section = selectOf('nq-field-section nq-pill-select', 'Section', editedSections().map((item) => [item.key, item.label]), field.section);
    const sources = tracking ? [['tracking', `Follow-up: ${state.trackingRefs[field.source_ref] || field.source_ref}`]]
      : Object.entries(state.fieldSources).filter(([key]) => key !== 'tracking');
    const source = selectOf('nq-field-source', 'Source of the value', sources, field.source);
    // A saved field keeps its source; a new one chooses it.
    source.disabled = tracking || Boolean(field.key);
    source.title = source.disabled ? 'Where the value comes from (fixed once the field is saved)' : 'Where the value comes from';
    const type = selectOf('nq-field-type', 'Type', Object.entries(state.fieldTypes), field.type || 'text');
    type.disabled = tracking;
    row.append(name, section, source, type);
    // Every field moves; only the follow-up fields stay.
    [['↑', 'Move up', () => moveVisible(block, -1)], ['↓', 'Move down', () => moveVisible(block, 1)],
      ['×', tracking ? 'The follow-up fields cannot be removed' : 'Remove', () => block.remove()]].forEach(([label, title, action], index) => {
      const button = node('button', label, 'nq-icon-action');
      button.type = 'button';
      button.title = title;
      button.setAttribute('aria-label', title);
      button.disabled = tracking && index === 2;
      button.addEventListener('click', action);
      row.append(button);
    });
    const flags = node('div', undefined, 'nq-field-flags');
    flags.append(
      flagToggle('in_table', 'Table column', tracking || field.in_table, tracking ? 'Always a column of the table' : 'Show the field as a column of the Calls table'),
      flagToggle('in_export', 'Excel', field.in_export !== false, 'Export the field to Excel, in the order of this list'),
      flagToggle('in_summary', 'Summary breakdown', field.in_summary, 'Count the calls of each value in the Summary (lists and Yes / No)'),
      flagToggle('required_to_close', 'Required to close', field.required_to_close, 'A call cannot move to a closed status while this field is empty'),
    );
    flags.querySelector('[data-flag="in_table"]').disabled = tracking;
    const more = node('details', undefined, 'nq-field-more');
    const summary = node('summary', 'Values and settings');
    const ref = node('label', undefined, 'nq-field-setting nq-field-ref');
    const refInput = textInput(field.source_ref, 'Value from', 'nq-field-ref-input');
    const listId = `nq-ref-list-${Math.random().toString(36).slice(2, 9)}`;
    const datalist = node('datalist');
    datalist.id = listId;
    refInput.setAttribute('list', listId);
    ref.append(node('span', 'Value from'), refInput, datalist);
    const suggest = node('label', undefined, 'nq-field-setting');
    suggest.append(node('span', 'Propose the CDR value of'), selectOf('nq-field-suggest', 'Propose the CDR value of',
      [['', 'Nothing'], ...state.callFields.map((item) => [item, item])], field.suggest_from || ''));
    const values = node('div', undefined, 'nq-field-values');
    const list = node('ul', undefined, 'nq-root-causes');
    const add = node('button', 'Add Value', 'nq-secondary-action');
    add.type = 'button';
    add.addEventListener('click', () => {
      const item = fieldValueRow(undefined, source.value === 'derived');
      list.append(item);
      item.querySelector('.nq-root-name').focus();
    });
    values.append(list, add);
    const description = textInput(field.description, 'Description (shown when hovering the field)', 'nq-field-description');
    more.append(summary, ref, suggest, values, description);
    const sync = () => {
      const kind = source.value;
      if (kind === 'derived') type.value = 'list';
      type.disabled = tracking || kind === 'derived';
      ref.hidden = tracking || kind === 'user';
      ref.querySelector('span').textContent = kind === 'derived' ? 'Call values read (comma separated)' : kind === 'rca' ? 'RCA script column' : 'CDR value';
      datalist.replaceChildren(...refChoices(kind).map(([value, text]) => {
        const option = node('option', text);
        option.value = value;
        return option;
      }));
      suggest.hidden = kind !== 'user';
      const lists = type.value === 'list' && ['user', 'derived'].includes(kind);
      values.hidden = !lists;
      const keywords = kind === 'derived';
      // The value rows show keywords only for derived lists.
      [...list.children].forEach((item) => {
        if (Boolean(item.querySelector('.nq-root-keywords')) !== keywords) {
          const option = {name: item.querySelector('.nq-root-name').value, keywords: item.querySelector('.nq-root-keywords')?.value.split(',') || [],
            color: item.querySelector('input[type="color"]').dataset.chosen ? item.querySelector('input[type="color"]').value : ''};
          const replacement = fieldValueRow(option, keywords);
          replacement.dataset.previous = item.dataset.previous;
          item.replaceWith(replacement);
        }
      });
      const summaryBox = flags.querySelector('[data-flag="in_summary"]');
      summaryBox.disabled = !['list', 'yes_no'].includes(type.value);
      if (summaryBox.disabled) summaryBox.checked = false;
      const required = flags.querySelector('[data-flag="required_to_close"]');
      required.disabled = kind !== 'user';
      if (required.disabled) required.checked = false;
      const count = list.children.length;
      summary.textContent = lists ? `Values (${count}) and settings` : 'Settings';
      const color = editedSection(section.value).color;
      block.style.setProperty('--nq-section', color);
      paintPill(section, color);
      block.dataset.section = section.value;
      block.dataset.source = kind;
    };
    list.append(...(field.options || []).map((option) => fieldValueRow(option, field.source === 'derived')));
    [type, source, section].forEach((control) => control.addEventListener('change', () => { sync(); filterFieldDefs(); }));
    list.addEventListener('click', () => window.requestAnimationFrame(sync));
    add.addEventListener('click', () => window.requestAnimationFrame(sync));
    sync();
    // New fields open their settings at once.
    more.open = !field.key;
    block.append(row, flags, more);
    return block;
  };
  const collectFields = () => [...$('nq-field-defs').children].map((block) => ({
    key: block.dataset.key || '',
    label: block.querySelector(':scope > .nq-option-row .nq-root-name').value.trim(),
    section: block.querySelector('.nq-field-section').value,
    source: block.querySelector('.nq-field-source').value,
    source_ref: block.querySelector('.nq-field-ref-input').value.trim(),
    type: block.querySelector('.nq-field-type').value,
    options: [...block.querySelectorAll('.nq-field-value')].map((row) => {
      const color = row.querySelector('input[type="color"]');
      return {name: row.querySelector('.nq-root-name').value.trim(), color: color.dataset.chosen ? color.value : '',
        previous: row.dataset.previous, keywords: row.querySelector('.nq-root-keywords')?.value || ''};
    }).filter((option) => option.name),
    in_table: block.querySelector('[data-flag="in_table"]').checked,
    in_export: block.querySelector('[data-flag="in_export"]').checked,
    in_summary: block.querySelector('[data-flag="in_summary"]').checked,
    required_to_close: block.querySelector('[data-flag="required_to_close"]').checked,
    suggest_from: block.querySelector('.nq-field-suggest').value,
    description: block.querySelector('.nq-field-description').value.trim(),
  }));
  // The section chips and the text filter show part of the fields; the order stays the order of every field.
  const filterFieldDefs = () => {
    const query = $('nq-field-filter').value.trim().toLowerCase();
    const blocks = [...$('nq-field-defs').children];
    blocks.forEach((block) => {
      const label = block.querySelector('.nq-root-name').value.toLowerCase();
      block.hidden = Boolean(fieldSection && block.dataset.section !== fieldSection) || Boolean(query && !label.includes(query));
    });
    const counts = {};
    blocks.forEach((block) => { counts[block.dataset.section] = (counts[block.dataset.section] || 0) + 1; });
    $('nq-field-section-chips').replaceChildren(...[{key: '', label: 'All', color: ''}, ...editedSections()].map((section) => {
      const chip = node('button', `${section.label} (${section.key ? counts[section.key] || 0 : blocks.length})`, 'nq-section-chip');
      chip.type = 'button';
      chip.setAttribute('role', 'tab');
      chip.setAttribute('aria-selected', String(fieldSection === section.key));
      chip.classList.toggle('is-active', fieldSection === section.key);
      if (section.color) chip.style.setProperty('--nq-section', section.color);
      chip.addEventListener('click', () => { fieldSection = section.key; filterFieldDefs(); });
      return chip;
    }));
  };
  const fillSectionsEditor = (sections) => {
    $('nq-sections-editor').replaceChildren(...sections.map((section) => {
      const row = node('div', undefined, 'nq-option-row nq-section-row');
      row.dataset.sectionKey = section.key;
      const color = node('input');
      color.type = 'color';
      color.value = section.color;
      color.setAttribute('aria-label', `Colour of ${section.label}`);
      const name = textInput(section.label, 'Section name');
      name.maxLength = 40;
      row.append(color, name);
      // Renamed or recoloured sections show at once in the fields.
      [color, name].forEach((control) => control.addEventListener('input', () => {
        $('nq-field-defs').querySelectorAll('.nq-field-section').forEach((select) => {
          const option = [...select.options].find((item) => item.value === section.key);
          if (option) option.textContent = name.value.trim() || section.key;
          select.dispatchEvent(new Event('change'));
        });
        filterFieldDefs();
      }));
      return row;
    }));
  };
  const fillFieldsDialog = () => {
    fillSectionsEditor(state.sections);
    $('nq-field-defs').replaceChildren(...state.fields.map((field) => fieldDefinition(field)));
    $('nq-field-filter').value = '';
    filterFieldDefs();
  };
  // A catalog workbook is previewed first; Import applies it.
  let catalogFile = null;
  const previewList = (label, names) => (names.length ? `${label}: ${names.slice(0, 12).join(', ')}${names.length > 12 ? ` +${names.length - 12}` : ''}` : '');
  const showCatalogPreview = (preview) => {
    const host = $('nq-catalog-preview');
    const lines = [
      `${preview.format === 'meeting' ? 'Field list of the meeting workbook' : 'Catalog workbook'} with ${number(preview.fields)} fields after the import.`,
      previewList('New fields', preview.added), previewList('Changed fields', preview.changed),
      previewList('New domains', preview.root_added.domains), previewList('New root categories', preview.root_added.categories),
      previewList('New root causes', preview.root_added.causes), previewList('New statuses', preview.statuses_added),
      previewList('New teams', preview.teams_added), preview.rules ? `${number(preview.rules)} Status Rules replace the current ones.` : '',
      preview.sections ? 'The section names and colours of the workbook are taken.' : '',
    ].filter(Boolean);
    const list = node('ul');
    list.append(...lines.map((line) => node('li', line)));
    const actions = node('div', undefined, 'nq-composer-actions');
    const cancel = node('button', 'Cancel', 'nq-secondary-action');
    const apply = node('button', 'Import', 'nq-primary-action');
    cancel.type = apply.type = 'button';
    cancel.addEventListener('click', () => { host.hidden = true; catalogFile = null; });
    apply.addEventListener('click', async () => {
      if (!catalogFile) return;
      apply.disabled = true;
      try {
        const body = new FormData();
        body.append('workbook', catalogFile);
        const response = await fetch('/api/non-qualified-calls/catalog/import', {method: 'POST', credentials: 'same-origin', body});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The catalog could not be imported.');
        host.hidden = true;
        catalogFile = null;
        toast('Catalog imported.');
        await loadState();
        fillFieldsDialog();
      } catch (error) {
        $('nq-fields-error').style.color = '';
        $('nq-fields-error').textContent = error.message;
      } finally {
        apply.disabled = false;
      }
    });
    actions.append(cancel, apply);
    host.replaceChildren(node('strong', `Import ${catalogFile?.name || 'the workbook'}?`), list, actions);
    host.hidden = false;
  };
  if (fieldsDialog) {
    $('nq-fields-open').addEventListener('click', () => {
      fieldSection = '';
      fillFieldsDialog();
      $('nq-catalog-preview').hidden = true;
      $('nq-fields-error').textContent = '';
      fieldsDialog.showModal();
    });
    $('nq-fields-cancel').addEventListener('click', () => fieldsDialog.close());
    $('nq-field-filter').addEventListener('input', filterFieldDefs);
    $('nq-field-defs').addEventListener('input', (event) => { if (event.target.matches('.nq-root-name')) filterFieldDefs(); });
    $('nq-fields-add').addEventListener('click', () => {
      const block = fieldDefinition();
      $('nq-field-defs').append(block);
      filterFieldDefs();
      block.querySelector('.nq-root-name').focus();
    });
    $('nq-fields-workbook').addEventListener('change', async (event) => {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      const message = $('nq-fields-error');
      message.style.color = 'var(--nq-muted)';
      message.textContent = 'Reading the workbook…';
      try {
        const body = new FormData();
        body.append('workbook', file);
        body.append('preview', '1');
        const response = await fetch('/api/non-qualified-calls/catalog/import', {method: 'POST', credentials: 'same-origin', body});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The workbook could not be read.');
        catalogFile = file;
        message.textContent = '';
        showCatalogPreview(payload);
      } catch (error) {
        message.style.color = '';
        message.textContent = error.message;
      }
    });
    $('nq-fields-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-fields-save');
      save.disabled = true;
      try {
        const sections = editedSections();
        if (JSON.stringify(sections) !== JSON.stringify(state.sections.map(({key, label, color}) => ({key, label, color})))) {
          await api('/api/non-qualified-calls/sections', {method: 'PUT', body: JSON.stringify({sections})});
        }
        await api('/api/non-qualified-calls/fields', {method: 'PUT', body: JSON.stringify({fields: collectFields()})});
        fieldsDialog.close();
        toast('Fields and sections saved.');
        await loadState();
        if (state.detail) openDetail(state.detail.call.call_key, {keepTab: true});
      } catch (error) {
        $('nq-fields-error').style.color = '';
        $('nq-fields-error').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
  }
  // -- table columns dialog -------------------------------------------------------------------
  const columnsDialog = $('nq-columns-dialog');
  const syncColumnCount = () => {
    const tableBoxes = [...columnsDialog.querySelectorAll('#nq-columns-cdr input[data-target="table"]')];
    const chosen = tableBoxes.filter((box) => box.checked).length;
    // A column of the table is always exported.
    tableBoxes.forEach((box) => {
      const excel = box.closest('.nq-cdr-column-row').querySelector('input[data-target="excel"]');
      if (box.checked) excel.checked = true;
      excel.disabled = box.checked;
      if (!box.checked) box.disabled = chosen >= state.maxCdrColumns;
    });
    const exported = columnsDialog.querySelectorAll('#nq-columns-cdr input[data-target="excel"]:checked').length;
    $('nq-columns-count').textContent = `(${chosen} of at most ${state.maxCdrColumns} in the table · ${exported} in Excel)`;
  };
  if (columnsDialog) {
    $('nq-columns-open').addEventListener('click', () => {
      const checkbox = (value, label, checked) => {
        const wrapper = node('label', undefined, 'nq-toggle');
        const box = node('input');
        box.type = 'checkbox';
        box.value = value;
        box.checked = checked;
        wrapper.append(box, ` ${label}`);
        return wrapper;
      };
      $('nq-columns-builtin').replaceChildren(...Object.entries(state.optionalColumns).map(([key, label]) => checkbox(key, label,
        state.tableColumns.builtin.includes(key))));
      // The catalog fields under their section; the follow-up ones always have their column.
      $('nq-columns-fields').replaceChildren(...state.sections.map((section) => {
        const fields = state.fields.filter((field) => field.section === section.key && field.source !== 'tracking');
        if (!fields.length) return null;
        const group = node('div', undefined, 'nq-columns-field-group');
        group.style.setProperty('--nq-section', section.color);
        group.append(sectionTag(section.key), ...fields.map((field) => {
          const option = checkbox(field.key, field.label, field.in_table);
          option.title = `${SOURCE_TAGS[field.source] || field.source} · ${field.description || field.label}`;
          return option;
        }));
        return group;
      }).filter(Boolean));
      const inTable = new Set(state.tableColumns.cdr);
      const inExcel = new Set(state.tableColumns.export_cdr || []);
      const names = [...new Set([...state.tableColumns.cdr, ...(state.tableColumns.export_cdr || []), ...state.cdrColumns])];
      const target = (name, kind, checked) => {
        const box = node('input');
        box.type = 'checkbox';
        box.value = name;
        box.dataset.target = kind;
        box.checked = checked;
        box.setAttribute('aria-label', `${name} in the ${kind === 'table' ? 'table' : 'Excel export'}`);
        return box;
      };
      $('nq-columns-cdr').replaceChildren(...names.map((name) => {
        const row = node('div', undefined, 'nq-cdr-column-row');
        row.dataset.name = name;
        row.append(node('span', name), target(name, 'table', inTable.has(name)), target(name, 'excel', inTable.has(name) || inExcel.has(name)));
        return row;
      }));
      if (!names.length) $('nq-columns-cdr').append(node('p', 'No CDR is indexed yet.', 'form-note'));
      $('nq-columns-search').value = '';
      $('nq-columns-error').textContent = '';
      syncColumnCount();
      columnsDialog.showModal();
    });
    $('nq-columns-cdr').addEventListener('change', syncColumnCount);
    $('nq-columns-search').addEventListener('input', () => {
      const query = $('nq-columns-search').value.trim().toLowerCase();
      $('nq-columns-cdr').querySelectorAll('.nq-cdr-column-row').forEach((row) => {
        row.hidden = Boolean(query) && !row.dataset.name.toLowerCase().includes(query);
      });
    });
    $('nq-columns-cancel').addEventListener('click', () => columnsDialog.close());
    $('nq-columns-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-columns-save');
      save.disabled = true;
      try {
        await api('/api/non-qualified-calls/table-columns', {method: 'PUT', body: JSON.stringify({
          builtin: [...$('nq-columns-builtin').querySelectorAll('input:checked')].map((box) => box.value),
          cdr: [...$('nq-columns-cdr').querySelectorAll('input[data-target="table"]:checked')].map((box) => box.value),
          export_cdr: [...$('nq-columns-cdr').querySelectorAll('input[data-target="excel"]:checked')]
            .filter((box) => !box.closest('.nq-cdr-column-row').querySelector('input[data-target="table"]').checked).map((box) => box.value),
        })});
        // The catalog fields chosen as columns are saved with the field catalog.
        const shown = new Set([...$('nq-columns-fields').querySelectorAll('input:checked')].map((box) => box.value));
        const listed = new Set([...$('nq-columns-fields').querySelectorAll('input')].map((box) => box.value));
        if (state.fields.some((field) => listed.has(field.key) && field.in_table !== shown.has(field.key))) {
          await api('/api/non-qualified-calls/fields', {method: 'PUT', body: JSON.stringify({fields: state.fields.map((field) => ({
            ...field, in_table: listed.has(field.key) ? shown.has(field.key) : field.in_table,
            options: field.options.map((option) => ({...option, previous: option.name})),
          }))})});
        }
        columnsDialog.close();
        toast('Additional columns saved.');
        await loadState();
      } catch (error) {
        $('nq-columns-error').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
  }
  // -- suggestion rule dialog (super-admins) ----------------------------------------------
  const ruleDialog = $('nq-rule-dialog');
  const fillRule = (rule) => {
    ruleDialog.querySelectorAll('[data-nq-rule-fields]').forEach((host) => {
      const chosen = new Set(rule[host.dataset.nqRuleFields] || []);
      host.replaceChildren(...Object.entries(state.ruleFields).map(([field, label]) => {
        const option = node('label', undefined, 'nq-toggle');
        const box = node('input');
        box.type = 'checkbox';
        box.value = field;
        box.checked = chosen.has(field);
        option.append(box, ` ${label}`);
        return option;
      }));
    });
    ruleDialog.querySelectorAll('input[data-nq-rule]').forEach((box) => { box.checked = Boolean(rule[box.dataset.nqRule]); });
    ruleDialog.querySelector('select[data-nq-rule="match"]').value = rule.match || 'words';
    $('nq-rule-error').textContent = '';
    // Everybody sees the rule; only admins and super-admins change it.
    const editable = Boolean(state.user.can_configure_rule);
    ruleDialog.querySelectorAll('input, select').forEach((control) => { control.disabled = !editable; });
    $('nq-rule-save').hidden = !editable;
    $('nq-rule-default').hidden = !editable;
    $('nq-rule-cancel').textContent = editable ? 'Cancel' : 'Close';
    $('nq-rule-readonly').hidden = editable;
  };
  const saveRule = async (rule) => {
    const save = $('nq-rule-save');
    save.disabled = true;
    try {
      const result = await api('/api/non-qualified-calls/root-causes/rule', {method: 'PUT', body: JSON.stringify({rule})});
      state.rootCauses.rule = result.rule;
      $('nq-root-rule-text').textContent = ruleText(result.rule);
      ruleDialog.close();
      toast('Suggestion rule saved.');
      loadCalls({quiet: true});
    } catch (error) {
      $('nq-rule-error').textContent = error.message;
    } finally {
      save.disabled = false;
    }
  };
  if (ruleDialog) {
    document.querySelectorAll('[data-nq-rule-open]').forEach((button) => button.addEventListener('click', () => {
      fillRule(state.rootCauses.rule);
      ruleDialog.showModal();
    }));
    $('nq-rule-cancel').addEventListener('click', () => ruleDialog.close());
    $('nq-rule-default').addEventListener('click', () => { if (state.defaultRule) fillRule(state.defaultRule); });
    $('nq-rule-form').addEventListener('submit', (event) => {
      event.preventDefault();
      const fields = (key) => [...ruleDialog.querySelectorAll(`[data-nq-rule-fields="${key}"] input:checked`)].map((box) => box.value);
      const rule = {domain_fields: fields('domain_fields'), cause_fields: fields('cause_fields'),
        match: ruleDialog.querySelector('select[data-nq-rule="match"]').value};
      ruleDialog.querySelectorAll('input[data-nq-rule]').forEach((box) => { rule[box.dataset.nqRule] = box.checked; });
      saveRule(rule);
    });
  }
  // -- Analysis Center menu -------------------------------------------------------------------
  const configMenu = $('nq-config-menu');
  const closeConfigMenu = () => {
    if (!configMenu || configMenu.hidden) return;
    configMenu.hidden = true;
    $('nq-config-toggle').setAttribute('aria-expanded', 'false');
  };
  if (configMenu) {
    // The menu opens where it fits: below the button, or above it near the bottom of the window, scrolling inside if needed,
    // and moved right when the button is too close to the left edge for it.
    const placeConfigMenu = () => {
      const button = $('nq-config-toggle').getBoundingClientRect();
      configMenu.style.maxHeight = '';
      configMenu.style.right = '';
      configMenu.classList.remove('is-up');
      const left = configMenu.getBoundingClientRect().left;
      if (left < 8) configMenu.style.right = `${left - 8}px`;
      const height = configMenu.scrollHeight;
      const below = window.innerHeight - button.bottom - 16;
      const above = button.top - 16;
      const up = height > below && above > below;
      configMenu.classList.toggle('is-up', up);
      configMenu.style.maxHeight = `${Math.max(160, up ? above : below)}px`;
    };
    $('nq-config-toggle').addEventListener('click', (event) => {
      event.stopPropagation();
      configMenu.hidden = !configMenu.hidden;
      $('nq-config-toggle').setAttribute('aria-expanded', String(!configMenu.hidden));
      if (!configMenu.hidden) {
        placeConfigMenu();
        configMenu.querySelector('button')?.focus({preventScroll: true});
      }
    });
    window.addEventListener('resize', () => { if (!configMenu.hidden) placeConfigMenu(); });
    // Every entry opens its dialog and closes the menu.
    configMenu.addEventListener('click', () => window.setTimeout(closeConfigMenu));
    document.addEventListener('click', (event) => { if (!configMenu.contains(event.target)) closeConfigMenu(); });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !configMenu.hidden) { closeConfigMenu(); $('nq-config-toggle').focus(); }
    });
  }

  // -- status rules dialog --------------------------------------------------------------------
  const statusRulesDialog = $('nq-status-rules-dialog');
  // The values a condition chooses among: list values, Yes / No, teams, users, root categories or causes.
  const conditionValues = (field) => {
    if (field === '@team') return state.options.teams.map((item) => item.name);
    if (field === '@assignee') return state.users;
    if (field === '@root_category') return state.rootCauses.categories.map((item) => item.name);
    if (field === '@root_cause') return state.rootCauses.causes.map((item) => item.name);
    return state.conditionFields[field]?.values || [];
  };
  const conditionColor = (field, name) => (field === '@team' ? optionColor('team', name)
    : field === '@root_category' ? optionColor('root_category', name) : field === '@root_cause' ? optionColor('root_cause', name)
      : optionColorOf(state.fields.find((item) => item.key === field) || {}, name));
  const conditionRow = (condition = {field: Object.keys(state.conditionFields)[0] || '', op: 'in', values: []}) => {
    const row = node('li', undefined, 'nq-condition');
    const field = selectOf('nq-condition-field', 'Field', Object.entries(state.conditionFields).map(([key, item]) => [key, item.label]),
      condition.field);
    const op = selectOf('nq-condition-op', 'Condition', Object.entries(state.ruleOperators), condition.op || 'in');
    const values = node('div', undefined, 'nq-condition-values');
    const fill = (chosen) => {
      const selected = new Set(chosen);
      const names = [...new Set([...conditionValues(field.value), ...chosen])];
      values.replaceChildren(...names.map((name) => {
        const label = node('label', undefined, 'nq-toggle nq-condition-value');
        const box = node('input');
        box.type = 'checkbox';
        box.value = name;
        box.checked = selected.has(name);
        const color = conditionColor(field.value, name);
        if (color) label.style.setProperty('--nq-chip', color);
        label.append(box, ` ${name}`);
        return label;
      }));
      if (!names.length) values.append(node('span', 'No values to choose.', 'nq-muted'));
      values.hidden = ['empty', 'not_empty'].includes(op.value);
    };
    field.addEventListener('change', () => fill([]));
    op.addEventListener('change', () => { values.hidden = ['empty', 'not_empty'].includes(op.value); });
    const remove = node('button', '×', 'nq-icon-action');
    remove.type = 'button';
    remove.title = 'Remove this condition';
    remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', () => row.remove());
    row.append(field, op, remove, values);
    fill(condition.values || []);
    return row;
  };
  const statusRuleBlock = (rule = {status: state.options.statuses[1]?.name || state.options.statuses[0]?.name || '', conditions: [undefined]}) => {
    const block = node('li', undefined, 'nq-root-domain nq-status-rule');
    const head = node('div', undefined, 'nq-option-row');
    // A default rule whose status was renamed or removed keeps its conditions and asks for the status.
    const known = state.options.statuses.some((item) => item.name === rule.status);
    const entries = state.options.statuses.map((item) => [item.name, item.name]);
    if (!known) entries.unshift(['', 'Choose a status…']);
    const status = selectOf('nq-rule-status nq-pill-select', 'Status', entries, known ? rule.status : '');
    const missing = known ? null : node('p', `The default rule sets ${rule.status}, which is not one of the statuses: choose the status it sets.`,
      'nq-rule-missing');
    const paint = () => {
      paintPill(status, optionColor('status', status.value));
      block.classList.toggle('is-missing', !status.value);
      if (missing) missing.hidden = Boolean(status.value);
    };
    status.addEventListener('change', paint);
    head.append(node('span', 'Set the status', 'nq-rule-word'), status, node('span', 'when every condition holds', 'nq-rule-word'));
    iconButtons(head, block, () => block.remove());
    const conditions = node('ul', undefined, 'nq-conditions');
    conditions.append(...(rule.conditions || []).map((condition) => conditionRow(condition)));
    const add = node('button', 'Add Condition', 'nq-link-action');
    add.type = 'button';
    add.addEventListener('click', () => conditions.append(conditionRow()));
    block.append(head, ...(missing ? [missing] : []), conditions, add);
    paint();
    return block;
  };
  const collectStatusRules = () => [...$('nq-status-rules').children].filter((block) => block.matches('.nq-status-rule')).map((block) => ({
    status: block.querySelector('.nq-rule-status').value,
    conditions: [...block.querySelectorAll('.nq-condition')].map((row) => ({
      field: row.querySelector('.nq-condition-field').value, op: row.querySelector('.nq-condition-op').value,
      values: [...row.querySelectorAll('.nq-condition-values input:checked')].map((box) => box.value),
    })),
  }));
  const fillStatusRules = (rules) => {
    $('nq-status-rules').replaceChildren(...rules.map((rule) => statusRuleBlock(rule)));
  };
  if (statusRulesDialog) {
    document.querySelectorAll('[data-nq-status-rules-open]').forEach((button) => button.addEventListener('click', () => {
      fillStatusRules(state.statusRules);
      $('nq-status-rules-error').textContent = '';
      statusRulesDialog.showModal();
    }));
    $('nq-status-rules-cancel').addEventListener('click', () => statusRulesDialog.close());
    $('nq-status-rules-add').addEventListener('click', () => {
      const block = statusRuleBlock();
      $('nq-status-rules').append(block);
      block.querySelector('select').focus();
    });
    // Every default rule, with the conditions on the fields this workspace still has; a rule whose status is not one of
    // the statuses asks for it.
    $('nq-status-rules-default').addEventListener('click', () => {
      const statuses = new Set(state.options.statuses.map((item) => item.name));
      const rules = (state.defaultStatusRules || [])
        .map((rule) => ({...rule, conditions: rule.conditions.filter((condition) => state.conditionFields[condition.field])}))
        .filter((rule) => rule.conditions.length);
      fillStatusRules(rules);
      const missing = [...new Set(rules.filter((rule) => !statuses.has(rule.status)).map((rule) => rule.status))];
      $('nq-status-rules-error').style.color = missing.length ? '' : 'var(--nq-muted)';
      $('nq-status-rules-error').textContent = missing.length
        ? `The default rules are shown. ${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} not among the statuses: choose the status of the marked rules (or put the default statuses back in Statuses & Teams), then Save.`
        : 'The default rules are shown: review them and Save.';
    });
    $('nq-status-rules-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-status-rules-save');
      save.disabled = true;
      try {
        if (collectStatusRules().some((rule) => !rule.status)) throw new Error('Choose the status of every rule.');
        await api('/api/non-qualified-calls/status-rules', {method: 'PUT', body: JSON.stringify({rules: collectStatusRules()})});
        statusRulesDialog.close();
        toast('Status Rules saved: the automatic statuses follow them.');
        await loadState();
        if (state.detail) openDetail(state.detail.call.call_key, {keepTab: true});
      } catch (error) {
        $('nq-status-rules-error').style.color = '';
        $('nq-status-rules-error').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
  }

  // -- RCA script results dialog ----------------------------------------------------------------
  const rcaDialog = $('nq-rca-dialog');
  let rcaFile = null;
  const smallTable = (headers, rows) => {
    const wrap = node('div', undefined, 'nq-table-wrap');
    const table = node('table', undefined, 'nq-table nq-stats-table');
    const head = node('thead');
    const headRow = node('tr');
    headRow.append(...headers.map((header) => node('th', header)));
    head.append(headRow);
    const body = node('tbody');
    rows.forEach((values) => {
      const row = node('tr');
      row.append(...values.map((value) => node('td', value)));
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    return wrap;
  };
  const renderRcaCurrent = (summary) => {
    const files = summary.files || [];
    const host = $('nq-rca-current');
    host.replaceChildren(node('h3', 'Imported results'), node('p', summary.total
      ? `${number(summary.total)} results by JOIN_ID; ${number(summary.matched)} match a Non-Qualified Call of this workspace.`
      : 'No result imported yet.', 'form-note'));
    if (files.length) {
      host.append(smallTable(['File', 'Results', 'Imported', 'By'], files.map((file) => [file.name, number(file.rows), exactTime(file.imported_at), file.imported_by])));
    }
    $('nq-rca-clear').hidden = !summary.total;
  };
  const renderRcaPreview = (preview) => {
    const host = $('nq-rca-preview');
    const facts = [
      `${number(preview.rows)} results by JOIN_ID: ${number(preview.matched)} match a call of this workspace and ${number(preview.unmatched)} do not (yet).`,
      $('nq-rca-replace').checked ? 'Every result imported before is forgotten.'
        : `${number(preview.new)} of them are new; the others replace the results of their JOIN_ID.`,
      `RCA columns: ${preview.columns.join(', ')}.`,
      preview.extra.length ? `Other columns kept with the call: ${preview.extra.join(', ')}.` : '',
      preview.skipped ? `${number(preview.skipped)} ${preview.skipped === 1 ? 'row' : 'rows'} without a JOIN_ID left out.` : '',
      preview.duplicates ? `${number(preview.duplicates)} repeated JOIN_IDs: the last row of each wins.` : '',
    ].filter(Boolean);
    const list = node('ul');
    list.append(...facts.map((fact) => node('li', fact)));
    const keys = Object.keys(state.rcaRefs).filter((key) => preview.preview.some((row) => row[key]));
    host.replaceChildren(node('h3', `Preview of ${preview.file_name}`), list,
      smallTable(['JOIN_ID', ...keys.map((key) => state.rcaRefs[key])], preview.preview.map((row) => [row.join_id, ...keys.map((key) => row[key] || '—')])));
    host.hidden = false;
  };
  const rcaRequest = async (preview) => {
    const body = new FormData();
    body.append('file', rcaFile);
    if ($('nq-rca-replace').checked) body.append('replace', '1');
    if (preview) body.append('preview', '1');
    const response = await fetch('/api/non-qualified-calls/rca/import', {method: 'POST', credentials: 'same-origin', body});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The RCA file could not be read.');
    return payload;
  };
  if (rcaDialog) {
    document.querySelectorAll('[data-nq-rca-open]').forEach((button) => button.addEventListener('click', async () => {
      rcaFile = null;
      $('nq-rca-format').textContent = state.rcaResults.format || '';
      $('nq-rca-preview').hidden = true;
      $('nq-rca-import').disabled = true;
      $('nq-rca-replace').checked = false;
      $('nq-rca-error').textContent = '';
      renderRcaCurrent(state.rcaResults);
      rcaDialog.showModal();
      try {
        state.rcaResults = await api('/api/non-qualified-calls/rca');
        renderRcaCurrent(state.rcaResults);
      } catch (_error) {
        // The summary of the page stays.
      }
    }));
    $('nq-rca-cancel').addEventListener('click', () => rcaDialog.close());
    // The preview tells what replacing the previous results means.
    $('nq-rca-replace').addEventListener('change', async () => {
      if (!rcaFile) return;
      try {
        renderRcaPreview(await rcaRequest(true));
      } catch (error) {
        $('nq-rca-error').textContent = error.message;
      }
    });
    $('nq-rca-file').addEventListener('change', async (event) => {
      rcaFile = event.target.files?.[0] || null;
      event.target.value = '';
      if (!rcaFile) return;
      $('nq-rca-error').style.color = 'var(--nq-muted)';
      $('nq-rca-error').textContent = `Reading ${rcaFile.name}…`;
      $('nq-rca-import').disabled = true;
      try {
        renderRcaPreview(await rcaRequest(true));
        $('nq-rca-error').textContent = '';
        $('nq-rca-import').disabled = false;
      } catch (error) {
        rcaFile = null;
        $('nq-rca-preview').hidden = true;
        $('nq-rca-error').style.color = '';
        $('nq-rca-error').textContent = error.message;
      }
    });
    $('nq-rca-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!rcaFile) return;
      const button = $('nq-rca-import');
      button.disabled = true;
      try {
        const result = await rcaRequest(false);
        toast(`${number(result.rows)} RCA results imported; ${number(result.matched)} match calls.`);
        rcaFile = null;
        $('nq-rca-preview').hidden = true;
        state.rcaResults = await api('/api/non-qualified-calls/rca');
        renderRcaCurrent(state.rcaResults);
        loadCalls({quiet: true});
        if (state.detail) openDetail(state.detail.call.call_key, {keepTab: true});
      } catch (error) {
        $('nq-rca-error').style.color = '';
        $('nq-rca-error').textContent = error.message;
        button.disabled = false;
      }
    });
    $('nq-rca-clear').addEventListener('click', async () => {
      const message = 'Delete every imported RCA script result? The calls lose their script values and recommendations from the script; their selected root cause stays.';
      const accepted = typeof window.showConfirmDialog === 'function'
        ? await window.showConfirmDialog(message, {title: 'Delete RCA results', confirmLabel: 'Delete'}) : window.confirm(message);
      if (!accepted) return;
      try {
        const result = await api('/api/non-qualified-calls/rca', {method: 'DELETE'});
        toast(`${number(result.deleted)} RCA results deleted.`);
        state.rcaResults = result.rca_results;
        renderRcaCurrent(state.rcaResults);
        loadCalls({quiet: true});
      } catch (error) {
        $('nq-rca-error').textContent = error.message;
      }
    });
  }
  // Keep the shared follow-up current while the page stays open.
  window.setInterval(() => {
    if (document.visibilityState !== 'visible' || state.busy) return;
    const active = document.activeElement;
    if (active && active.closest?.('#nq-table select, #nq-drawer textarea, #nq-drawer select, #nq-drawer input, .nq-comment-editor')) return;
    if (Object.keys(changedFields()).length) return;
    if (rootPicker || document.querySelector('dialog[open]')) return;
    loadCalls({quiet: true});
    if (state.detail && !composerBody.value.trim() && !drawer.querySelector('.nq-comment-editor')) openDetail(state.detail.call.call_key, {keepTab: true});
  }, REFRESH_INTERVAL_MS);

  loadState();
})();
