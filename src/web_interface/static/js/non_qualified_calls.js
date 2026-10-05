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
    service: 'Service', campaign: 'Campaign', operator: 'Operator', vendor: 'Vendor', region: 'Region', city: 'City',
    technology: 'Technology', test_name: 'Test Name', result: 'Result', failure_classification: 'Failure Classification',
    failure_category: 'Failure Category', status: 'Status', team: 'Team', assignee: 'Assignee', datasets: 'CDR',
  };
  const HISTORY_LABELS = {status: 'Status', team: 'Team', assignee: 'Assignee'};
  const REFRESH_INTERVAL_MS = 60000;

  const state = {
    options: {statuses: [], teams: []}, users: [], user: {username: '', can_edit: false, can_moderate: false},
    unassigned: '__unassigned__', datasets: [], sort: 'start_time', direction: 'desc', page: 1, pageSize: 50,
    result: null, selected: new Set(), detail: null, requestToken: 0, busy: false,
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
    };
    filterSelects().forEach((select) => {
      const field = select.dataset.nqFilter;
      fillSelect(select, entries[field] || (values[field] || []).map((value) => [value, value]));
    });
  };
  const currentFilters = () => {
    const filters = {};
    filterSelects().forEach((select) => {
      const enabled = [...select.options];
      const chosen = enabled.filter((option) => option.selected).map((option) => option.value);
      // Every value or none means no restriction.
      if (chosen.length && chosen.length < enabled.length) filters[select.dataset.nqFilter] = chosen;
    });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { if (box.checked) filters[box.dataset.nqFlag] = true; });
    const search = $('nq-search').value.trim();
    if (search) filters.search = search;
    return filters;
  };
  const selectOnly = (field, value) => {
    const select = root.querySelector(`[data-nq-filter="${field}"]`);
    if (!select) return;
    const target = field === 'team' || field === 'assignee' ? (value || state.unassigned) : value;
    const chosen = [...select.selectedOptions].map((option) => option.value);
    const toggleOff = chosen.length === 1 && chosen[0] === target;
    [...select.options].forEach((option) => { option.selected = !toggleOff && option.value === target; });
    select.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const clearFilter = (field) => {
    if (field === 'search') { $('nq-search').value = ''; scheduleLoad(); return; }
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
    Object.entries(filters).forEach(([field, value]) => {
      let text;
      if (field === 'search') text = `Search: “${value}”`;
      else if (flagLabels[field]) text = flagLabels[field];
      else {
        const select = root.querySelector(`[data-nq-filter="${field}"]`);
        const labels = value.map((item) => [...(select?.options || [])].find((option) => option.value === item)?.textContent || item);
        text = `${FIELD_LABELS[field] || field}: ${labels.length > 3 ? `${labels.slice(0, 3).join(', ')} +${labels.length - 3}` : labels.join(', ')}`;
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
      ['Non-Qualified Calls', number(summary.total), 'Calls and tests that did not complete', 'total'],
      ['Open', number(summary.open), `${percent(summary.open, summary.total)} still under follow-up`, 'open'],
      ['Closed', number(summary.closed), `${percent(summary.closed, summary.total)} resolved or not applicable`, 'closed'],
      ['With Team', number(summary.with_team), `${percent(summary.with_team, summary.total)} have a responsible team`, 'team'],
      ['Commented', number(summary.commented), `${percent(summary.commented, summary.total)} have comments`, 'commented'],
    ];
    $('nq-kpis').replaceChildren(...cards.map(([label, value, note, kind]) => {
      const card = node('article', undefined, `nq-kpi nq-kpi-${kind}`);
      card.append(node('span', label, 'nq-kpi-label'), node('strong', value), node('span', note, 'nq-kpi-note'));
      return card;
    }));
    const filters = currentFilters();
    $('nq-breakdowns').replaceChildren(...result.breakdowns.map((breakdown) => {
      const card = node('section', undefined, 'nq-breakdown');
      card.append(node('h3', breakdown.label));
      const max = Math.max(1, ...breakdown.items.map((item) => item.count));
      if (!breakdown.items.length) card.append(node('p', 'No calls.', 'form-note'));
      breakdown.items.forEach((item) => {
        const field = breakdown.field;
        const label = field === 'service' ? (SERVICE_LABELS[item.value] || item.value)
          : item.value || (field === 'team' ? 'Unassigned' : 'Not classified');
        const row = node('button', undefined, 'nq-bar');
        row.type = 'button';
        const filterValue = (field === 'team' && !item.value) ? state.unassigned : item.value;
        const active = (filters[field] || []).length === 1 && filters[field][0] === filterValue;
        row.classList.toggle('is-active', active);
        row.title = active ? `Remove the ${FIELD_LABELS[field]} filter` : `Show only ${label}`;
        const track = node('span', undefined, 'nq-bar-track');
        const fill = node('span', undefined, 'nq-bar-fill');
        fill.style.width = `${Math.max(2, (item.count / max) * 100)}%`;
        const color = field === 'status' ? optionColor('status', item.value) : field === 'team' ? optionColor('team', item.value) : '';
        if (color) fill.style.background = color;
        track.append(fill);
        row.append(node('span', label, 'nq-bar-label'), track, node('span', number(item.count), 'nq-bar-count'));
        row.addEventListener('click', () => {
          if (field === 'failure_classification' && !item.value) return;
          selectOnly(field, item.value);
        });
        card.append(row);
      });
      return card;
    }));
  };

  // -- table ------------------------------------------------------------------
  const trackingSelect = (kind, call) => {
    const select = node('select', undefined, `nq-pill-select nq-pill-${kind}`);
    select.setAttribute('aria-label', `${HISTORY_LABELS[kind]} of the call`);
    const entries = kind === 'status' ? state.options.statuses.map((item) => [item.name, item.name])
      : kind === 'team' ? [['', 'Unassigned'], ...state.options.teams.map((item) => [item.name, item.name])]
        : [['', 'Unassigned'], ...state.users.map((name) => [name, name])];
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
  const textCell = (value, className = '') => node('td', value || '—', className);
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
      const service = node('td');
      service.append(node('span', call.service_label, `nq-service nq-service-${call.service}`));
      const result = node('td');
      result.append(node('span', call.result || '—', `nq-result ${resultClass(call.result)}`));
      const failure = node('td', undefined, 'nq-failure');
      if (call.failure_classification || call.failure_category) {
        failure.append(node('strong', call.failure_classification || call.failure_category));
        if (call.failure_classification && call.failure_category) failure.append(node('span', call.failure_category));
        failure.title = [call.failure_subcategory, call.failure_comment].filter(Boolean).join('\n');
      } else {
        failure.append(node('span', 'Not classified', 'nq-muted'));
      }
      const tracking = (kind) => {
        const cell = node('td', undefined, 'nq-tracking-cell');
        cell.append(state.user.can_edit ? trackingSelect(kind, call) : pill(kind, call[kind]));
        return cell;
      };
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
      comments.append(commentButton);
      const open = node('td', undefined, 'nq-open-cell');
      const openButton = node('button', '›', 'nq-open-button');
      openButton.type = 'button';
      openButton.setAttribute('aria-label', 'Open the call details and activity');
      open.append(openButton);
      const start = textCell(cdrTime(call.start_time), 'nq-nowrap');
      // Two related values share a cell: the main one first, the other below it.
      const stacked = (main, secondary) => {
        const cell = node('td', undefined, 'nq-stacked');
        cell.append(node('strong', main || '—'));
        if (secondary) cell.append(node('span', secondary));
        cell.title = [main, secondary].filter(Boolean).join(' · ');
        return cell;
      };
      row.append(
        service, start, stacked(call.operator, call.vendor), stacked(call.city, call.campaign),
        stacked(call.test_name, call.technology), result, failure, tracking('status'), tracking('team'),
        tracking('assignee'), comments, open,
      );
      row.addEventListener('click', (event) => {
        if (event.target.closest('select, input, a')) return;
        openDetail(call.call_key);
      });
      return row;
    }));
  };
  const renderSortHeaders = () => {
    $('nq-table').querySelectorAll('th[data-sort]').forEach((header) => {
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
  const renderBulk = () => {
    const bulk = $('nq-bulk');
    if (!bulk) return;
    bulk.hidden = !state.selected.size;
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
      renderSummary(result);
      renderRows(result);
      renderSortHeaders();
      renderPagination(result);
      renderBulk();
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

  async function loadState() {
    try {
      const payload = await api('/api/non-qualified-calls/state');
      state.options = payload.options;
      state.users = payload.users || [];
      state.user = payload.user;
      state.unassigned = payload.unassigned || state.unassigned;
      state.datasets = payload.datasets || [];
      renderSync(payload.sync);
      fillFilters(payload);
      fillBulkSelects();
      await loadCalls();
    } catch (error) {
      $('nq-sync').textContent = error.message;
      $('nq-count').textContent = error.message;
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
      text.append(who, ` changed ${HISTORY_LABELS[kind] || kind} `);
      if (entry.old_value) text.append('from ', pill(kind, entry.old_value), ' ');
      text.append('to ', pill(kind, entry.new_value));
    }
    const time = node('time', relativeTime(entry.changed_at));
    time.title = exactTime(entry.changed_at);
    text.append(' · ', time);
    item.append(text);
    return item;
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
    host.replaceChildren(field('status', 'Status'), field('team', 'Team'), field('assignee', 'Assignee'), updated);
  };
  const DETAIL_FIELDS = [
    ['Service', 'service_label'], ['Result', 'result'], ['Operator', 'operator'], ['Vendor', 'vendor'], ['Campaign', 'campaign'],
    ['NR Mode', 'nr_mode'], ['Region', 'region'], ['City', 'city'], ['Technology', 'technology'], ['Test Name', 'test_name'],
    ['Direction', 'direction'], ['Start Time', 'start_time'], ['End Time', 'end_time'], ['Failure Phase', 'failure_phase'],
    ['Failure Technology', 'failure_technology'], ['Failure Classification', 'failure_classification'],
    ['Failure Category', 'failure_category'], ['Failure Subcategory', 'failure_subcategory'],
    ['Failure Comment', 'failure_comment'], ['Cell ID', 'cell_id'], ['CDR', 'dataset_name'],
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
  function renderDetail(detail) {
    state.detail = detail;
    const call = detail.call;
    $('nq-drawer-eyebrow').replaceChildren(
      node('span', call.service_label, `nq-service nq-service-${call.service}`), ' ',
      node('span', call.result || '—', `nq-result ${resultClass(call.result)}`),
    );
    $('nq-drawer-title').textContent = [call.operator, call.campaign].filter(Boolean).join(' · ') || 'Call details';
    $('nq-drawer-meta').textContent = [cdrTime(call.start_time), call.city, call.technology, call.test_name].filter((value) => value && value !== '—').join(' · ');
    renderTracking(call);
    const events = [
      ...detail.comments.map((comment) => ({time: comment.created_at, item: timelineComment(comment)})),
      ...detail.history.map((entry) => ({time: entry.changed_at, item: timelineChange(entry)})),
    ].sort((a, b) => String(a.time).localeCompare(String(b.time)));
    const timeline = $('nq-timeline');
    timeline.replaceChildren(...events.map((event) => event.item));
    if (!events.length) timeline.append(node('li', state.user.can_edit ? 'No activity yet. Start the follow-up with a comment.' : 'No activity yet.', 'nq-empty-timeline'));
    const grid = $('nq-detail-grid');
    grid.replaceChildren();
    DETAIL_FIELDS.forEach(([label, key]) => {
      const value = key.endsWith('_time') ? cdrTime(call[key]) : call[key];
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
      closed: Boolean(row.querySelector('.nq-option-closed input')?.checked)};
  });

  // -- events -------------------------------------------------------------------
  root.addEventListener('change', (event) => {
    if (event.target.matches('[data-nq-filter], [data-nq-flag]')) scheduleLoad();
  });
  $('nq-search').addEventListener('input', debounce(() => { state.page = 1; loadCalls(); }, 400));
  $('nq-reset').addEventListener('click', () => {
    filterSelects().forEach((select) => { [...select.options].forEach((option) => { option.selected = false; }); select.dispatchEvent(new Event('change')); });
    root.querySelectorAll('[data-nq-flag]').forEach((box) => { box.checked = false; });
    $('nq-search').value = '';
    scheduleLoad();
  });
  $('nq-refresh').addEventListener('click', () => loadState());
  $('nq-page-size').addEventListener('change', (event) => { state.pageSize = Number(event.target.value) || 50; state.page = 1; loadCalls(); });
  $('nq-table').querySelectorAll('th[data-sort]').forEach((header) => {
    header.tabIndex = 0;
    const sort = () => {
      if (state.sort === header.dataset.sort) state.direction = state.direction === 'asc' ? 'desc' : 'asc';
      else { state.sort = header.dataset.sort; state.direction = header.dataset.sort === 'start_time' ? 'desc' : 'asc'; }
      state.page = 1;
      loadCalls();
    };
    header.addEventListener('click', sort);
    header.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); } });
  });
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
        state.selected.clear();
        loadCalls({quiet: true});
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  });
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
    if (event.key === 'Escape' && drawer.classList.contains('is-open') && !optionsDialog?.open) closeDrawer();
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
  // Keep the shared follow-up current while the page stays open.
  window.setInterval(() => {
    if (document.visibilityState !== 'visible' || state.busy) return;
    const active = document.activeElement;
    if (active && active.closest?.('#nq-table select, #nq-drawer textarea, #nq-drawer select, .nq-comment-editor')) return;
    loadCalls({quiet: true});
    if (state.detail && !composerBody.value.trim() && !drawer.querySelector('.nq-comment-editor')) openDetail(state.detail.call.call_key, {keepTab: true});
  }, REFRESH_INTERVAL_MS);

  loadState();
})();
