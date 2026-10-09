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
    root_domain: 'Root Domain', root_cause: 'Root Cause', nr_mode: 'NR Mode', call_type: 'Call Type', period: 'Period',
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
    assigned: 'Assigned', commented: 'Commented', labelled: 'With a root cause', suggested: 'Suggested root cause'};
  // Filters set by clicking the Progress View and the Root Cause Analysis; they have no select of their own.
  const EXTRA_FILTERS = ['nr_mode', 'call_type', 'period', 'age', 'root_pair', 'effective_domain', 'effective_cause', 'node',
    'state', 'rca_state'];
  const HISTORY_LABELS = {status: 'Status', team: 'Team', assignee: 'Assignee', root_domain: 'Root Domain', root_cause: 'Root Cause'};
  // The label of a changed field: a follow-up field or an analysis field ("field:key").
  const historyLabel = (field) => (field.startsWith('field:')
    ? (state.fields.find((item) => item.key === field.slice(6))?.label || field.slice(6)) : (HISTORY_LABELS[field] || field));
  const NOT_CLASSIFIED = 'Not classified';
  // Campaigns as the workspace Campaign Maps show them (campaign_labels.js); filters keep the full value.
  const campaignLabel = (value) => (globalThis.campaignLabel ? globalThis.campaignLabel(value) : String(value ?? ''));
  // A root cause travels in selects as "domain||cause" (the cause may be empty).
  const ROOT_SEPARATOR = '||';
  const REFRESH_INTERVAL_MS = 60000;

  const state = {
    options: {statuses: [], teams: []}, rootCauses: {domains: [], require_to_close: false}, users: [],
    user: {username: '', can_edit: false, can_moderate: false},
    unassigned: '__unassigned__', datasets: [], mainCities: [], sort: 'start_time', direction: 'desc', page: 1, pageSize: 50,
    result: null, selected: new Set(), detail: null, requestToken: 0, busy: false, extraFilters: {},
    fields: [], fieldTypes: {}, tableColumns: {builtin: [], cdr: []}, optionalColumns: {}, cdrColumns: [], versionLabels: {},
    rateService: '',
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
  const optionColor = (kind, name) => {
    if (kind === 'root_domain' || kind === 'root_cause') return state.rootCauses.domains.find((item) => item.name === name)?.color || '';
    const list = kind === 'status' ? state.options.statuses : state.options.teams;
    return list.find((item) => item.name === name)?.color || '';
  };
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
  const pill = (kind, name, emptyLabel = 'Unassigned') => {
    const element = node('span', name || emptyLabel, `nq-pill nq-pill-${kind}`);
    paintPill(element, kind === 'assignee' ? '' : optionColor(kind, name));
    if (!name) element.classList.add('is-empty');
    return element;
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
      root_cause: [...new Set(state.rootCauses.domains.flatMap((item) => item.causes.map((cause) => cause.name)))].map((name) => [name, name]),
      version: Object.entries(state.versionLabels),
    };
    // A filter for every list and Yes / No analysis field, after the others.
    const fieldHost = $('nq-field-filters');
    const filterable = state.fields.filter((field) => ['list', 'yes_no'].includes(field.type));
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
    const target = ['team', 'assignee', 'root_domain'].includes(field) ? (value || state.unassigned) : value;
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
  const renderActiveFilters = (filters) => {
    const host = $('nq-active-filters');
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
      const chip = node('button', text, 'nq-filter-chip');
      chip.type = 'button';
      chip.title = 'Remove this filter';
      chip.append(node('span', '×', 'nq-filter-chip-x'));
      chip.addEventListener('click', () => clearFilter(field));
      chips.push(chip);
    });
    host.replaceChildren(...chips);
    host.hidden = !chips.length;
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
            : item.label || item.value || (field === 'team' ? 'Unassigned' : field.startsWith('field:') ? 'Empty' : NOT_CLASSIFIED);
        const row = node('button', undefined, 'nq-bar');
        row.type = 'button';
        const isField = field.startsWith('field:');
        const filterValue = ((['team', 'root_domain'].includes(field) || isField) && !item.value) ? state.unassigned : item.value;
        const chosen = filterValues(filters, field) || [];
        const active = chosen.length === 1 && chosen[0] === filterValue;
        row.classList.toggle('is-active', active);
        row.title = active ? `Remove the ${FIELD_LABELS[field]} filter` : `Show only ${label}`;
        const track = node('span', undefined, 'nq-bar-track');
        const fill = node('span', undefined, 'nq-bar-fill');
        fill.style.width = `${Math.max(2, (item.count / max) * 100)}%`;
        // The colours of the PowerPoint and Word: the status, team or domain colour, else the palette in order.
        const color = (['status', 'team', 'root_domain'].includes(field) ? optionColor(field, item.value) : '')
          || breakdown.colors?.[item.value] || PALETTE[index % PALETTE.length];
        fill.style.background = color;
        track.append(fill);
        row.append(node('span', label, 'nq-bar-label'), track, node('span', number(item.count), 'nq-bar-count'));
        row.addEventListener('click', () => {
          if (!item.value && !['team', 'assignee', 'root_domain'].includes(field) && !isField) return;
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
    if (field === 'root_cause') {
      // Causes under their domain; a cause shared by two domains is the same value in both.
      const byValue = new Map(options.map((option) => [option.value, option]));
      boxes = [];
      state.rootCauses.domains.forEach((domain) => {
        const causes = domain.causes.map((cause) => byValue.get(cause.name)).filter(Boolean);
        if (!causes.length) return;
        const heading = node('p', domain.name, 'nq-column-filter-group');
        heading.style.setProperty('--nq-group', optionColor('root_domain', domain.name) || '#b8c0c6');
        list.append(heading);
        const group = causes.map(checkbox);
        headings.push([heading, group]);
        boxes.push(...group);
      });
      // Twin boxes of a shared cause follow each other.
      list.addEventListener('change', (event) => {
        const changed = event.target;
        if (changed.type !== 'checkbox') return;
        boxes.forEach(([, box]) => { if (box !== changed && box.value === changed.value) box.checked = changed.checked; });
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
  const trackingSelect = (kind, call) => {
    const select = node('select', undefined, `nq-pill-select nq-pill-${kind}`);
    select.setAttribute('aria-label', `${HISTORY_LABELS[kind]} of the call`);
    const entries = kind === 'status' ? state.options.statuses.map((item) => [item.name, item.name])
      : kind === 'team' ? [['', 'Unassigned'], ...state.options.teams.map((item) => [item.name, item.name])]
        : [['', 'Unassigned'], ...assignableUsers(call.team).map((name) => [name, name])];
    const current = call[kind] || '';
    if (current && !entries.some(([value]) => value === current)) entries.push([current, current]);
    select.append(...entries.map(([value, label]) => {
      const option = node('option', label);
      option.value = value;
      option.selected = value === current;
      return option;
    }));
    const paint = () => {
      paintPill(select, kind === 'assignee' ? '' : optionColor(kind, select.value));
      select.classList.toggle('is-empty', !select.value);
      select.title = `${HISTORY_LABELS[kind]}: ${select.value || 'Unassigned'}`;
    };
    paint();
    select.addEventListener('change', async () => {
      paint();
      select.disabled = true;
      try {
        const detail = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
          method: 'PATCH', body: JSON.stringify({changes: {[kind]: select.value}, version: call.version}),
        });
        Object.assign(call, detail.call);
        if (state.detail?.call.call_key === call.call_key) renderDetail(detail);
        toast(`${HISTORY_LABELS[kind]} updated.`);
        loadCalls({quiet: true});
      } catch (error) {
        toast(error.message, 'error');
        loadCalls({quiet: true});
      } finally {
        select.disabled = false;
      }
    });
    select.addEventListener('click', (event) => event.stopPropagation());
    return select;
  };
  const rootLabel = (domain, cause) => (domain ? [domain, cause].filter(Boolean).join(' · ') : NOT_CLASSIFIED);
  const suggestionText = (suggestion) => `Suggested${suggestion.source === 'comments' ? ' from comments' : ''}: ${rootLabel(suggestion.domain, suggestion.cause)}`;
  const rootEntries = () => state.rootCauses.domains.map((domain) => [domain.name, [
    [`${domain.name}${ROOT_SEPARATOR}`, `${domain.name} (no cause)`],
    ...domain.causes.map((cause) => [`${domain.name}${ROOT_SEPARATOR}${cause.name}`, cause.name]),
  ]]);
  const saveRootCause = async (call, changes, control) => {
    if (control) control.disabled = true;
    try {
      const detail = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
        method: 'PATCH', body: JSON.stringify({changes, version: call.version}),
      });
      Object.assign(call, detail.call);
      if (state.detail?.call.call_key === call.call_key) renderDetail(detail);
      toast('Root cause updated.');
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      if (control) control.disabled = false;
      loadCalls({quiet: true});
    }
  };
  // The root cause of a call: a select grouped by domain, and the suggested root cause while it has none.
  // Cause picker: the domains as coloured headings with their causes, like the column filters.
  let causePicker = null;
  const closeCausePicker = () => {
    causePicker?.popover.remove();
    causePicker = null;
  };
  const placeCausePicker = () => {
    if (!causePicker) return;
    const rect = causePicker.anchor.getBoundingClientRect();
    if (!causePicker.anchor.isConnected || rect.bottom < 0 || rect.top > window.innerHeight) { closeCausePicker(); return; }
    const {popover} = causePicker;
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    // Open downwards, or upwards when there is clearly more room above.
    const up = below < 260 && above > below;
    popover.style.maxHeight = `${Math.max(180, up ? above : below)}px`;
    popover.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - popover.offsetWidth - 8))}px`;
    popover.style.top = up ? `${Math.max(8, rect.top - 4 - popover.offsetHeight)}px` : `${rect.bottom + 4}px`;
  };
  const openCausePicker = (anchor, call, choose) => {
    closeCausePicker();
    const popover = node('div', undefined, 'nq-column-filter nq-cause-picker');
    popover.setAttribute('role', 'listbox');
    popover.setAttribute('aria-label', 'Root cause');
    popover.addEventListener('click', (event) => event.stopPropagation());
    const search = node('input');
    search.type = 'search';
    search.placeholder = 'Search causes…';
    const list = node('div', undefined, 'nq-column-filter-list');
    const groups = state.rootCauses.domains.map((domain) => {
      const heading = node('p', domain.name, 'nq-column-filter-group');
      heading.style.setProperty('--nq-group', domain.color || '#b8c0c6');
      list.append(heading);
      const items = [['', 'No cause'], ...domain.causes.map((cause) => [cause.name, cause.name])].map(([cause, text]) => {
        const option = node('button', text, 'nq-cause-option');
        option.type = 'button';
        option.setAttribute('role', 'option');
        const selected = domain.name === call.root_domain && cause === (call.root_cause || '');
        option.classList.toggle('is-selected', selected);
        option.classList.toggle('is-empty', !cause);
        option.setAttribute('aria-selected', String(selected));
        option.addEventListener('click', () => {
          closeCausePicker();
          if (!selected) choose(domain.name, cause);
        });
        list.append(option);
        return [option, text, domain.name];
      });
      return [heading, items];
    });
    search.addEventListener('input', () => {
      const text = search.value.trim().toLowerCase();
      groups.forEach(([heading, items]) => {
        items.forEach(([option, label, domain]) => {
          option.hidden = Boolean(text) && !`${domain} ${label}`.toLowerCase().includes(text);
        });
        heading.hidden = items.every(([option]) => option.hidden);
      });
    });
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        list.querySelector('.nq-cause-option:not([hidden])')?.click();
      }
    });
    popover.append(search, list);
    document.body.append(popover);
    causePicker = {popover, anchor};
    placeCausePicker();
    // Show the current cause; only the list scrolls (scrollIntoView would also scroll the page).
    const current = list.querySelector('.is-selected');
    if (current) list.scrollTop = current.offsetTop - list.clientHeight / 2;
    search.focus({preventScroll: true});
  };
  document.addEventListener('click', (event) => { if (causePicker && !causePicker.popover.contains(event.target)) closeCausePicker(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && causePicker) { event.stopPropagation(); causePicker.anchor.focus(); closeCausePicker(); }
  }, true);
  window.addEventListener('scroll', (event) => {
    if (causePicker && !causePicker.popover.contains(event.target)) window.requestAnimationFrame(placeCausePicker);
  }, {passive: true, capture: true});
  window.addEventListener('resize', closeCausePicker);
  // The root cause of a call: its domain above and the cause of that domain below, or the
  // suggested root cause below while it has none.
  const rootCauseControl = (call) => {
    const wrapper = node('div', undefined, 'nq-root-cell');
    const suggestion = call.suggested_root_cause;
    const suggestionNote = () => {
      if (call.root_domain || !suggestion) return null;
      if (!state.user.can_edit) return node('span', suggestionText(suggestion), 'nq-root-suggestion');
      const apply = node('button', suggestionText(suggestion), 'nq-root-suggestion');
      apply.type = 'button';
      apply.title = `${suggestionText(suggestion)}\n${suggestion.source === 'comments'
        ? 'Set this root cause, suggested by the comments of the call' : 'Set this root cause, suggested by the CDR failure classification'}`;
      apply.addEventListener('click', (event) => {
        event.stopPropagation();
        saveRootCause(call, {root_domain: suggestion.domain, root_cause: suggestion.cause}, apply);
      });
      return apply;
    };
    if (!state.user.can_edit) {
      const domain = pill('root_domain', call.root_domain, NOT_CLASSIFIED);
      wrapper.append(domain);
      if (call.root_domain) {
        const cause = pill('root_cause', call.root_cause, 'No cause');
        paintPill(cause, '');
        wrapper.append(cause);
      }
      const note = suggestionNote();
      if (note) wrapper.append(note);
      return wrapper;
    }
    const selectOf = (label, entries, current) => {
      const select = node('select', undefined, 'nq-pill-select nq-root-select');
      select.setAttribute('aria-label', label);
      if (current && !entries.some(([value]) => value === current)) entries.push([current, current]);
      select.append(...entries.map(([value, text]) => {
        const option = node('option', text);
        option.value = value;
        return option;
      }));
      select.value = current;
      select.addEventListener('click', (event) => event.stopPropagation());
      return select;
    };
    const domainSelect = selectOf('Root domain of the call',
      [['', NOT_CLASSIFIED], ...state.rootCauses.domains.map((item) => [item.name, item.name])], call.root_domain || '');
    paintPill(domainSelect, optionColor('root_domain', call.root_domain));
    domainSelect.classList.toggle('is-empty', !call.root_domain);
    domainSelect.title = `Root Domain: ${call.root_domain || NOT_CLASSIFIED}`;
    // A new domain starts without a cause: its causes are different.
    domainSelect.addEventListener('change', () => saveRootCause(call, {root_domain: domainSelect.value, root_cause: ''}, domainSelect));
    wrapper.append(domainSelect);
    if (call.root_domain) {
      // Every domain, in its colour, with its causes: a cause of another domain changes the domain too.
      const picker = node('button', call.root_cause || 'No cause', 'nq-pill-select nq-root-select nq-cause-picker-button');
      picker.type = 'button';
      picker.setAttribute('aria-haspopup', 'listbox');
      picker.setAttribute('aria-label', 'Root cause of the call');
      picker.classList.toggle('is-empty', !call.root_cause);
      picker.title = `Cause: ${rootLabel(call.root_domain, call.root_cause || 'No cause')}`;
      picker.addEventListener('click', (event) => {
        event.stopPropagation();
        if (causePicker?.anchor === picker) { closeCausePicker(); return; }
        openCausePicker(picker, call, (domain, cause) => saveRootCause(call, {root_domain: domain, root_cause: cause}, picker));
      });
      wrapper.append(picker);
    }
    const note = suggestionNote();
    if (note) wrapper.append(note);
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
  const fieldColumns = () => state.fields.filter((field) => field.in_table);
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
  const headerCell = (label, sortKey, filterKey = '') => {
    const cell = node('th', undefined, 'nq-sort-pair nq-dynamic-col');
    const item = node('span', undefined, 'nq-header-item');
    const name = node('span', label);
    name.dataset.sort = sortKey;
    if (filterKey) name.dataset.filter = filterKey;
    item.append(name);
    cell.append(item);
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
    anchor = after('root_cause');
    fieldColumns().forEach((field) => {
      const filterable = ['list', 'yes_no'].includes(field.type) ? `field:${field.key}` : '';
      const cell = headerCell(field.label, `field:${field.key}`, filterable);
      anchor.after(cell);
      anchor = cell;
    });
    naturalColumns = [...row.cells].map(columnKeyOf).filter(Boolean);
    applyColumnOrder();
  };
  const saveFieldValue = async (call, key, value, control) => {
    if (control) control.disabled = true;
    try {
      const detail = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
        method: 'PATCH', body: JSON.stringify({changes: {fields: {[key]: value}}, version: call.version}),
      });
      Object.assign(call, detail.call);
      if (state.detail?.call.call_key === call.call_key) renderDetail(detail);
      toast(`${historyLabel(`field:${key}`)} updated.`);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      if (control) control.disabled = false;
      loadCalls({quiet: true});
    }
  };
  // A list or Yes / No field is chosen in the row; the other fields are shown and edited in the call.
  const fieldCell = (call, field) => {
    const cell = node('td', undefined, 'nq-tracking-cell nq-field-cell');
    const value = call.fields?.[field.key] || '';
    if (['list', 'yes_no'].includes(field.type) && state.user.can_edit) {
      const select = node('select', undefined, 'nq-pill-select nq-field-select');
      select.setAttribute('aria-label', `${field.label} of the call`);
      const choices = field.type === 'yes_no' ? ['Yes', 'No'] : field.options.map((option) => option.name);
      if (value && !choices.includes(value)) choices.push(value);
      select.append(node('option', '—'), ...choices.map((choice) => {
        const option = node('option', choice);
        option.value = choice;
        return option;
      }));
      select.options[0].value = '';
      select.value = value;
      const paint = () => {
        paintPill(select, optionColorOf(field, select.value));
        select.classList.toggle('is-empty', !select.value);
        select.title = `${field.label}: ${select.value || 'empty'}`;
      };
      paint();
      select.addEventListener('click', (event) => event.stopPropagation());
      select.addEventListener('change', () => { paint(); saveFieldValue(call, field.key, select.value, select); });
      cell.append(select);
      return cell;
    }
    if (['list', 'yes_no'].includes(field.type) && value) {
      const element = node('span', value, 'nq-pill');
      paintPill(element, optionColorOf(field, value));
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
      start.append(node('span', cdrTime(call.start_time), 'nq-nowrap'),
        node('span', call.service_label, `nq-service nq-service-${call.service}`));
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
      const updated = node('span', call.updated_at ? `Updated ${relativeTime(call.updated_at)}${call.updated_by ? ` by ${call.updated_by}` : ''}` : 'Not followed up yet',
        'nq-status-updated');
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
        root, ...fieldColumns().map((field) => fieldCell(call, field)), tracking('team', 'assignee'), status, comments,
      );
      orderRowCells(row);
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
      const element = node('button', label, current ? 'is-current' : '');
      element.type = 'button';
      element.disabled = disabled;
      if (current) element.setAttribute('aria-current', 'page');
      element.addEventListener('click', () => { state.page = page; loadCalls(); });
      return element;
    };
    const pages = new Set([1, result.pages, result.page - 1, result.page, result.page + 1]);
    const items = [button('‹ Previous', result.page - 1, result.page <= 1)];
    let previous = 0;
    [...pages].filter((page) => page >= 1 && page <= result.pages).sort((a, b) => a - b).forEach((page) => {
      if (page - previous > 1) items.push(node('span', '…', 'nq-ellipsis'));
      items.push(button(String(page), page, false, page === result.page));
      previous = page;
    });
    items.push(button('Next ›', result.page + 1, result.page >= result.pages));
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
    bulk.hidden = !state.selected.size;
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
    fill('nq-bulk-status', 'Set status…', state.options.statuses.map((item) => [item.name, item.name]));
    fill('nq-bulk-team', 'Set team…', [[state.unassigned, 'Unassigned'], ...state.options.teams.map((item) => [item.name, item.name])]);
    fill('nq-bulk-assignee', 'Assign to…', [[state.unassigned, 'Unassigned'], ...state.users.map((name) => [name, name])]);
    const fieldSelect = $('nq-bulk-field');
    if (fieldSelect) {
      const choosable = state.fields.filter((field) => ['list', 'yes_no'].includes(field.type));
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
    const root = $('nq-bulk-root');
    if (root) {
      root.replaceChildren(node('option', 'Set root cause…'), node('option', NOT_CLASSIFIED));
      root.options[0].value = '';
      root.options[1].value = state.unassigned;
      rootEntries().forEach(([domain, entries]) => {
        const group = node('optgroup');
        group.label = domain;
        group.append(...entries.map(([value, label]) => {
          const option = node('option', label);
          option.value = value;
          return option;
        }));
        root.append(group);
      });
    }
  };

  // -- loading ----------------------------------------------------------------
  const renderSync = (sync) => {
    if (!sync) return;
    const when = sync.synced_at ? ` · indexed ${relativeTime(sync.synced_at)}` : '';
    $('nq-sync').textContent = `${number(sync.calls)} Non-Qualified Calls in ${number(sync.datasets)} CDRs${when}`;
    $('nq-sync').title = sync.synced_at ? `CDRs last indexed ${exactTime(sync.synced_at)}` : '';
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
      const result = await api('/api/non-qualified-calls/calls', {
        method: 'POST',
        body: JSON.stringify({filters, sort: state.sort, direction: state.direction, page: state.page, page_size: state.pageSize}),
      });
      if (token !== state.requestToken) return;
      state.result = result;
      state.page = result.page;
      renderSync(result.sync);
      renderActiveFilters(filters);
      renderColumnFilters();
      renderSummary(result);
      renderRows(result);
      renderSortHeaders();
      renderPagination(result);
      renderBulk();
      void loadProgress();
      void loadRootCauses();
      void loadRates();
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

  async function loadState() {
    try {
      const payload = await api('/api/non-qualified-calls/state');
      state.options = payload.options;
      state.rootCauses = payload.root_causes || state.rootCauses;
      state.rootCauseDefaults = payload.root_cause_defaults || [];
      state.ruleFields = payload.root_cause_rule_fields || {};
      state.defaultRule = payload.default_root_cause_rule || null;
      state.users = payload.users || [];
      state.user = payload.user;
      state.unassigned = payload.unassigned || state.unassigned;
      state.datasets = payload.datasets || [];
      state.mainCities = payload.main_cities || [];
      state.fields = payload.fields || [];
      state.fieldTypes = payload.field_types || {};
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
    drawer.querySelectorAll('[data-nq-tab]').forEach((tab) => {
      const active = tab.dataset.nqTab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    drawer.querySelectorAll('[data-nq-panel]').forEach((panel) => { panel.hidden = panel.dataset.nqPanel !== name; });
  };
  const timelineChange = (entry) => {
    const item = node('li', undefined, 'nq-event nq-event-change');
    item.append(node('span', '', 'nq-event-dot'));
    const text = node('p');
    const who = node('strong', entry.changed_by);
    if (entry.field === 'comment_edit') text.append(who, ' edited a comment');
    else if (entry.field === 'comment_delete') text.append(who, ' deleted a comment');
    else {
      const kind = entry.field;
      const emptyLabel = kind.startsWith('root_') ? NOT_CLASSIFIED : 'Unassigned';
      const historyPill = (value) => {
        const element = pill(kind, value, emptyLabel);
        if (kind === 'root_cause') paintPill(element, '');
        return element;
      };
      if (kind.startsWith('field:')) {
        const field = state.fields.find((item) => item.key === kind.slice(6));
        const fieldPill = (value) => {
          const element = node('span', value || 'empty', `nq-pill${value ? '' : ' is-empty'}`);
          if (field) paintPill(element, optionColorOf(field, value));
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
  const renderTracking = (call) => {
    const host = $('nq-drawer-tracking');
    const field = (kind, label) => {
      const wrapper = node('label', undefined, 'nq-tracking-field');
      wrapper.append(node('span', label));
      wrapper.append(state.user.can_edit ? trackingSelect(kind, call) : pill(kind, call[kind]));
      return wrapper;
    };
    const updated = node('p', call.updated_by
      ? `Last follow-up by ${call.updated_by} · ${exactTime(call.updated_at)}` : 'Not followed up yet.', 'nq-tracking-note');
    const root = node('div', undefined, 'nq-tracking-field nq-tracking-root');
    root.append(node('span', 'Root Cause'), rootCauseControl(call));
    host.replaceChildren(field('status', 'Status'), field('team', 'Team'), field('assignee', 'Assignee'), root, updated);
  };
  const DETAIL_FIELDS = [
    ['Service', 'service_label'], ['Result', 'result'], ['Operator', 'operator'], ['Vendor', 'vendor'], ['Campaign', 'campaign'],
    ['NR Mode', 'nr_mode'], ['Region', 'region'], ['City', 'city'], ['Technology', 'technology'], ['Test Name', 'test_name'],
    ['Session Type', 'session_type'], ['Direction', 'direction'], ['Start Time', 'start_time'], ['End Time', 'end_time'],
    ['Failure Phase', 'failure_phase'],
    ['Failure Technology', 'failure_technology'], ['Failure Classification', 'failure_classification'],
    ['Failure Category', 'failure_category'], ['Failure Subcategory', 'failure_subcategory'],
    ['Failure Comment', 'failure_comment'], ['Cell ID', 'cell_id'], ['Root Domain', 'root_domain'], ['Root Cause', 'root_cause'],
    ['JOIN_ID', 'join_id'], ['CDR', 'dataset_name'],
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
  // The analysis fields of the call (or Speech sample), edited together and saved with its version.
  const fieldInput = (field, value) => {
    let control;
    if (field.type === 'list' || field.type === 'yes_no') {
      control = node('select');
      const choices = field.type === 'yes_no' ? ['Yes', 'No'] : field.options.map((option) => option.name);
      if (value && !choices.includes(value)) choices.push(value);
      control.append(node('option', '—'), ...choices.map((choice) => {
        const option = node('option', choice);
        option.value = choice;
        return option;
      }));
      control.options[0].value = '';
      control.value = value;
      const paint = () => paintPill(control, optionColorOf(field, control.value));
      control.classList.add('nq-pill-select');
      paint();
      control.addEventListener('change', paint);
    } else if (field.type === 'long_text') {
      control = node('textarea');
      control.rows = 3;
      control.maxLength = 2000;
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
  const renderAnalysis = (detail) => {
    const form = $('nq-analysis-form');
    const call = detail.call;
    if (!state.fields.length) {
      form.replaceChildren(node('p', state.user.can_edit
        ? 'No analysis fields yet: add the fields of your follow-up with Analysis Fields, above the table.'
        : 'This workspace has no analysis fields.', 'form-note'));
    } else {
      const grid = node('div', undefined, 'nq-analysis-grid');
      state.fields.forEach((field) => {
        const wrapper = node('label', undefined, `nq-analysis-field is-${field.type}`);
        const title = node('span', field.label);
        if (field.required_to_close) title.append(node('small', ' · required to close', 'nq-muted'));
        if (field.description) wrapper.title = field.description;
        wrapper.append(title, fieldInput(field, call.fields?.[field.key] || ''));
        grid.append(wrapper);
      });
      const actions = node('div', undefined, 'nq-composer-actions');
      const note = node('span', '', 'nq-composer-note');
      const save = node('button', 'Save Analysis', 'nq-primary-action');
      save.type = 'submit';
      save.hidden = !state.user.can_edit;
      actions.append(note, save);
      form.replaceChildren(grid, actions);
      form.onsubmit = async (event) => {
        event.preventDefault();
        const changes = {};
        form.querySelectorAll('[data-field-key]').forEach((control) => {
          if (control.value !== control.dataset.original) changes[control.dataset.fieldKey] = control.value;
        });
        if (!Object.keys(changes).length) { note.textContent = 'Nothing to save.'; return; }
        save.disabled = true;
        try {
          const updated = await api(`/api/non-qualified-calls/calls/${encodeURIComponent(call.call_key)}`, {
            method: 'PATCH', body: JSON.stringify({changes: {fields: changes}, version: call.version}),
          });
          renderDetail(updated);
          selectTab('analysis');
          toast('Analysis saved.');
          loadCalls({quiet: true});
        } catch (error) {
          note.textContent = '';
          toast(error.message, 'error');
        } finally {
          save.disabled = false;
        }
      };
    }
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
      tracking.append(pill('status', sample.status), node('span', rootLabel(sample.root_domain, sample.root_cause), 'nq-muted'),
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
    renderAnalysis(detail);
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
    if (!keepTab) selectTab('activity');
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
  $('nq-reset').addEventListener('click', () => {
    filterSelects().forEach((select) => { [...select.options].forEach((option) => { option.selected = false; }); select.dispatchEvent(new Event('change')); });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { box.checked = false; });
    root.querySelectorAll('[data-nq-typed-filter]').forEach((input) => { input.value = ''; });
    state.extraFilters = {};
    $('nq-search').value = '';
    scheduleLoad();
  });
  // Reindex: the calls of every CDR are indexed again (their follow-up is kept), then the page reloads them.
  $('nq-refresh').addEventListener('click', async () => {
    const button = $('nq-refresh');
    button.disabled = true;
    globalThis.showLoadingOverlay?.('Reindexing Non-Qualified Calls', 'Indexing the calls of every CDR again. Their follow-up is kept.');
    try {
      await api('/api/non-qualified-calls/reindex', {method: 'POST'});
      await loadState();
    } catch (error) {
      $('nq-sync').textContent = error.message;
    } finally {
      globalThis.hideLoadingOverlay?.();
      button.disabled = false;
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
  [['nq-bulk-status', 'status'], ['nq-bulk-team', 'team'], ['nq-bulk-assignee', 'assignee']].forEach(([id, kind]) => {
    $(id)?.addEventListener('change', async (event) => {
      const value = event.target.value;
      if (!value) return;
      const target = value === state.unassigned ? '' : value;
      const label = target || 'Unassigned';
      event.target.value = '';
      const count = state.selected.size;
      const accepted = typeof window.showConfirmDialog === 'function'
        ? await window.showConfirmDialog(`Set ${HISTORY_LABELS[kind]} to “${label}” for ${number(count)} selected calls?`, {title: 'Change selected calls', confirmLabel: 'Apply'})
        : window.confirm(`Set ${HISTORY_LABELS[kind]} to “${label}” for ${count} selected calls?`);
      if (!accepted) return;
      try {
        const result = await api('/api/non-qualified-calls/calls/bulk', {
          method: 'POST', body: JSON.stringify({call_keys: [...state.selected], changes: {[kind]: target}}),
        });
        toast(`${number(result.changed)} calls updated.`);
        loadCalls({quiet: true});
      } catch (error) {
        toast(error.message, 'error');
      }
    });
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
  $('nq-bulk-root')?.addEventListener('change', async (event) => {
    const value = event.target.value;
    if (!value) return;
    event.target.value = '';
    const [domain = '', cause = ''] = value === state.unassigned ? [] : value.split(ROOT_SEPARATOR);
    if (!await confirmBulk(`Set the root cause to “${rootLabel(domain, cause)}” for ${number(state.selected.size)} selected calls?`)) return;
    bulkChange({root_domain: domain, root_cause: cause});
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
    if (!await confirmBulk(`Label the ${number(state.selected.size)} selected calls without a root cause with their suggested root cause?`)) return;
    bulkChange({apply_suggestion: true});
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
    if (event.key === 'Escape' && drawer.classList.contains('is-open') && !optionsDialog?.open && !$('nq-root-dialog')?.open
      && !$('nq-rule-dialog')?.open && !$('nq-fields-dialog')?.open && !$('nq-columns-dialog')?.open) closeDrawer();
  });
  drawer.querySelectorAll('[data-nq-tab]').forEach((tab) => tab.addEventListener('click', () => selectTab(tab.dataset.nqTab)));
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
  const causeRow = (cause = {name: '', keywords: []}) => {
    const row = node('li', undefined, 'nq-option-row nq-root-cause');
    row.dataset.previous = cause.name || '';
    row.append(textInput(cause.name, 'Cause name', 'nq-root-name'), textInput((cause.keywords || []).join(', '), 'Keywords', 'nq-root-keywords'));
    iconButtons(row, row, () => row.remove());
    return row;
  };
  const domainBlock = (domain = {name: '', color: '#6a63c9', keywords: [], causes: []}) => {
    const block = node('li', undefined, 'nq-root-domain');
    block.dataset.previous = domain.name || '';
    const row = node('div', undefined, 'nq-option-row');
    const color = node('input');
    color.type = 'color';
    color.value = domain.color || '#6a63c9';
    color.setAttribute('aria-label', 'Colour');
    row.append(color, textInput(domain.name, 'Domain name', 'nq-root-name'), textInput((domain.keywords || []).join(', '), 'Keywords', 'nq-root-keywords'));
    iconButtons(row, block, () => block.remove());
    const causes = node('ul', undefined, 'nq-root-causes');
    causes.append(...(domain.causes || []).map((cause) => causeRow(cause)));
    const add = node('button', 'Add Cause', 'nq-secondary-action');
    add.type = 'button';
    add.addEventListener('click', () => {
      const cause = causeRow();
      causes.append(cause);
      cause.querySelector('input').focus();
    });
    block.append(row, causes, add);
    return block;
  };
  const collectRootCauses = () => [...$('nq-root-domains').children].map((block) => {
    const row = block.querySelector(':scope > .nq-option-row');
    return {
      name: row.querySelector('.nq-root-name').value.trim(), previous: block.dataset.previous,
      color: row.querySelector('input[type="color"]').value, keywords: row.querySelector('.nq-root-keywords').value,
      causes: [...block.querySelectorAll('.nq-root-cause')].map((cause) => ({
        name: cause.querySelector('.nq-root-name').value.trim(), previous: cause.dataset.previous,
        keywords: cause.querySelector('.nq-root-keywords').value,
      })),
    };
  });
  if (rootDialog) {
    $('nq-root-open').addEventListener('click', () => {
      $('nq-root-rule-text').textContent = ruleText(state.rootCauses.rule);
      $('nq-root-domains').replaceChildren(...state.rootCauses.domains.map((domain) => domainBlock(domain)));
      $('nq-root-require').checked = Boolean(state.rootCauses.require_to_close);
      $('nq-root-error').textContent = '';
      rootDialog.showModal();
    });
    $('nq-root-cancel').addEventListener('click', () => rootDialog.close());
    // Adds the default domains and causes that are missing; existing ones keep their keywords.
    $('nq-root-defaults').addEventListener('click', () => {
      const list = $('nq-root-domains');
      const nameOf = (element) => element.querySelector('.nq-root-name').value.trim().toLowerCase();
      let added = 0;
      (state.rootCauseDefaults || []).forEach((domain) => {
        const block = [...list.children].find((item) => nameOf(item.querySelector(':scope > .nq-option-row')) === domain.name.toLowerCase());
        if (!block) { list.append(domainBlock(domain)); added += 1 + domain.causes.length; return; }
        const causes = block.querySelector('.nq-root-causes');
        const names = new Set([...causes.children].map(nameOf));
        domain.causes.filter((cause) => !names.has(cause.name.toLowerCase())).forEach((cause) => { causes.append(causeRow(cause)); added += 1; });
      });
      $('nq-root-error').style.color = 'var(--nq-muted)';
      $('nq-root-error').textContent = added ? `${added} default values added: review them and Save.` : 'Every default domain and cause is already in the list.';
    });
    $('nq-root-add').addEventListener('click', () => {
      const block = domainBlock();
      $('nq-root-domains').append(block);
      block.querySelector('.nq-root-name').focus();
    });
    $('nq-root-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('nq-root-save');
      save.disabled = true;
      try {
        await api('/api/non-qualified-calls/root-causes', {
          method: 'PUT', body: JSON.stringify({domains: collectRootCauses(), require_to_close: $('nq-root-require').checked}),
        });
        rootDialog.close();
        toast('Root causes saved.');
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
  // -- analysis fields dialog ---------------------------------------------------------------
  const fieldsDialog = $('nq-fields-dialog');
  const fieldValueRow = (option = {name: '', color: ''}) => {
    const row = node('li', undefined, 'nq-option-row nq-field-value');
    row.dataset.previous = option.name || '';
    const color = node('input');
    color.type = 'color';
    color.value = /^#[0-9a-f]{6}$/i.test(option.color || '') ? option.color : '#b8c0c6';
    color.dataset.chosen = option.color ? '1' : '';
    color.title = 'Colour of the value';
    color.addEventListener('input', () => { color.dataset.chosen = '1'; });
    row.append(color, textInput(option.name, 'Value', 'nq-root-name'));
    iconButtons(row, row, () => row.remove());
    return row;
  };
  const fieldDefinition = (field = {key: '', label: '', type: 'list', options: [], in_table: false, in_summary: false,
    required_to_close: false, description: ''}) => {
    const block = node('li', undefined, 'nq-root-domain nq-field-def');
    block.dataset.key = field.key || '';
    const row = node('div', undefined, 'nq-option-row');
    const type = node('select', undefined, 'nq-field-type');
    type.setAttribute('aria-label', 'Type');
    Object.entries(state.fieldTypes).forEach(([value, label]) => {
      const option = node('option', label);
      option.value = value;
      type.append(option);
    });
    type.value = field.type || 'text';
    row.append(textInput(field.label, 'Field name', 'nq-root-name'), type);
    iconButtons(row, block, () => block.remove());
    const values = node('div', undefined, 'nq-field-values');
    const list = node('ul', undefined, 'nq-root-causes');
    list.append(...(field.options || []).map((option) => fieldValueRow(option)));
    const add = node('button', 'Add Value', 'nq-secondary-action');
    add.type = 'button';
    add.addEventListener('click', () => {
      const item = fieldValueRow();
      list.append(item);
      item.querySelector('.nq-root-name').focus();
    });
    values.append(list, add);
    const flags = node('div', undefined, 'nq-field-flags');
    const flag = (name, label, checked, title) => {
      const wrapper = node('label', undefined, 'nq-toggle');
      const box = node('input');
      box.type = 'checkbox';
      box.dataset.flag = name;
      box.checked = Boolean(checked);
      wrapper.title = title;
      wrapper.append(box, ` ${label}`);
      return wrapper;
    };
    flags.append(
      flag('in_table', 'Column in the table', field.in_table, 'Show the field as a column of the Calls table'),
      flag('in_summary', 'Breakdown in the Summary', field.in_summary, 'Count the calls of each value in the Summary (lists and Yes / No)'),
      flag('required_to_close', 'Required to close', field.required_to_close, 'A call cannot move to a closed status while this field is empty'),
    );
    const description = textInput(field.description, 'Description (shown when hovering the field)', 'nq-field-description');
    const sync = () => {
      values.hidden = type.value !== 'list';
      const summary = flags.querySelector('[data-flag="in_summary"]');
      summary.disabled = !['list', 'yes_no'].includes(type.value);
      if (summary.disabled) summary.checked = false;
    };
    type.addEventListener('change', sync);
    sync();
    block.append(row, values, flags, description);
    return block;
  };
  const collectFields = () => [...$('nq-field-defs').children].map((block) => ({
    key: block.dataset.key || '',
    label: block.querySelector(':scope > .nq-option-row .nq-root-name').value.trim(),
    type: block.querySelector('.nq-field-type').value,
    options: [...block.querySelectorAll('.nq-field-value')].map((row) => {
      const color = row.querySelector('input[type="color"]');
      return {name: row.querySelector('.nq-root-name').value.trim(), color: color.dataset.chosen ? color.value : '',
        previous: row.dataset.previous};
    }).filter((option) => option.name),
    in_table: block.querySelector('[data-flag="in_table"]').checked,
    in_summary: block.querySelector('[data-flag="in_summary"]').checked,
    required_to_close: block.querySelector('[data-flag="required_to_close"]').checked,
    description: block.querySelector('.nq-field-description').value.trim(),
  }));
  if (fieldsDialog) {
    $('nq-fields-open').addEventListener('click', () => {
      $('nq-field-defs').replaceChildren(...state.fields.map((field) => fieldDefinition(field)));
      $('nq-fields-error').textContent = '';
      fieldsDialog.showModal();
    });
    $('nq-fields-cancel').addEventListener('click', () => fieldsDialog.close());
    $('nq-fields-add').addEventListener('click', () => {
      const block = fieldDefinition();
      $('nq-field-defs').append(block);
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
        const response = await fetch('/api/non-qualified-calls/fields/from-excel', {method: 'POST', credentials: 'same-origin', body});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The workbook could not be read.');
        const present = new Set(collectFields().map((field) => field.label.toLowerCase()));
        const added = (payload.fields || []).filter((field) => !present.has(field.label.toLowerCase()));
        added.forEach((field) => $('nq-field-defs').append(fieldDefinition(field)));
        const skipped = payload.skipped?.length ? ` Left out (they come from the CDR or a script): ${payload.skipped.join(', ')}.` : '';
        message.textContent = `${added.length} fields added from ${file.name}: review their types and values, then Save.${skipped}`;
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
        await api('/api/non-qualified-calls/fields', {method: 'PUT', body: JSON.stringify({fields: collectFields()})});
        fieldsDialog.close();
        toast('Analysis fields saved.');
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
  // Keep the shared follow-up current while the page stays open.
  window.setInterval(() => {
    if (document.visibilityState !== 'visible' || state.busy) return;
    const active = document.activeElement;
    if (active && active.closest?.('#nq-table select, #nq-drawer textarea, #nq-drawer select, #nq-drawer input, .nq-comment-editor')) return;
    if ([...document.querySelectorAll('#nq-analysis-form [data-field-key]')].some((control) => control.value !== control.dataset.original)) return;
    if (causePicker) return;
    loadCalls({quiet: true});
    if (state.detail && !composerBody.value.trim() && !drawer.querySelector('.nq-comment-editor')) openDetail(state.detail.call.call_key, {keepTab: true});
  }, REFRESH_INTERVAL_MS);

  loadState();
})();
