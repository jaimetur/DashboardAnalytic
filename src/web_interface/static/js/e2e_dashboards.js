/* One filter DOM and one definition are shared between the page and the overlay. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('ds-config').textContent);
  let dashboards = {}, activeId = '', definition = null, savedDefinition = '', appliedFilterState = '', prepared = null, slideIndex = 0;
  let sequence = 0, timer, controller, preparing = null, dirty = false, filterActionBusy = false, dataIndex = 0, dataPage = 0, dataToken = '', dataRequest = 0;
  const dataPages = new Map();
  let presentationTimer = 0;
  const presentation = {running: false, delay: 5000, effect: 'fade'};
  let facetOptions = {}, availableFields = [], facetFields = config.filter_fields || [], facetsLoading = false, facetsRefreshTimer = 0;
  const completedFieldJobs = new Set();
  const chartPayloads = new Map();
  const renderedChartPayloads = new Map();
  const preparedPayloads = new Map();
  const dashboardStatuses = new Map();
  let dashboardStatusRefreshing = false;
  let expandedChartRequest = 0;
  let backgroundPreparationToken = '';
  let dateBounds = null, templateEditorSaved = false, templateEditorPreloadTimer = 0;
  const openStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:open`;
  const libraryStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:library`;
  const preparedStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:prepared`;
  const dashboardId = () => {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  };
  const rememberOpen = id => { try { if (id) sessionStorage.setItem(openStorageKey, id); else sessionStorage.removeItem(openStorageKey); } catch (_) { /* Storage is optional. */ } };
  const rememberLibrary = () => { try { sessionStorage.setItem(libraryStorageKey, JSON.stringify(dashboards)); } catch (_) { /* Storage is optional. */ } };
  const nextName = value => { let name = value, number = 2; while (Object.values(dashboards).some(item => item.name.toLowerCase() === name.toLowerCase())) name = `${value.slice(0, 108)} (${number++})`; return name; };
  const focusReturn = new Map();
  const status = message => { $('ds-status').textContent = message; };
  const backgroundWorkspaceName = () => document.querySelector('[data-header-active-workspace-name]')?.textContent?.trim() || 'Active workspace';
  const emitPreparationStatus = (statusValue, detail = '', token = backgroundPreparationToken) => {
    if (!token || token !== backgroundPreparationToken) return;
    window.dispatchEvent(new CustomEvent('dashboard-analytic:background-task', {detail: {
      id: 'e2e-dashboard-preparation', workspace_id: config.workspace, workspace_name: backgroundWorkspaceName(), is_active: true,
      label: 'Preparing Dashboard data and filters', detail, progress: null, status: statusValue,
    }}));
  };
  const dismissPreparationStatus = () => {
    if (!backgroundPreparationToken) return;
    emitPreparationStatus('complete');
    backgroundPreparationToken = '';
  };
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
  const option = (value, label) => { const el = node('option', label); el.value = value; return el; };
  const identity = value => String(value).toLocaleLowerCase().replace(/[^a-z0-9]/g, '');
  const canonicalDashboardDefinition = value => {
    const definitionValue = structuredClone(value || {});
    definitionValue.datasets ||= {};
    for (const kind of ['data', 'voice', 'speech']) definitionValue.datasets[kind] ||= [];
    definitionValue.filters ||= {};
    definitionValue.custom_fields ||= [];
    definitionValue.hidden_filters ||= [];
    definitionValue.slide_comments ||= {};
    return definitionValue;
  };
  const canonicalize = value => {
    if (Array.isArray(value)) return value.map(canonicalize);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
  };
  const definitionFingerprint = value => JSON.stringify(canonicalize(canonicalDashboardDefinition(value)));
  const hasUnsavedDashboardChanges = (ignoredFields = []) => {
    if (!definition) return false;
    const current = canonicalDashboardDefinition(definition);
    let saved;
    try { saved = canonicalDashboardDefinition(JSON.parse(savedDefinition || '{}')); }
    catch (_) { return true; }
    for (const field of ignoredFields) current[field] = saved[field];
    return definitionFingerprint(current) !== definitionFingerprint(saved);
  };
  const savedDashboardDefinition = () => {
    try { return canonicalDashboardDefinition(JSON.parse(savedDefinition || '{}')); }
    catch (_error) { return {}; }
  };
  const sameFilterValues = (left, right) => JSON.stringify([...(left || [])].sort()) === JSON.stringify([...(right || [])].sort());
  const hasUnsavedFilter = field => !sameFilterValues(definition?.filters?.[field], savedDashboardDefinition().filters?.[field]);
  const hasUnsavedSource = kind => !sameFilterValues(definition?.datasets?.[kind], savedDashboardDefinition().datasets?.[kind]);
  const hasUnsavedScope = () => String(definition?.scope || '') !== String(savedDashboardDefinition().scope || '');
  const hasUnsavedDate = key => String(definition?.[key] || '') !== String(savedDashboardDefinition()[key] || '');
  const filterStateFingerprint = value => JSON.stringify(canonicalize({
    datasets: value?.datasets || {}, scope: value?.scope || 'single', filters: value?.filters || {},
    custom_fields: value?.custom_fields || [], hidden_filters: value?.hidden_filters || [],
    date_from: value?.date_from || null, date_to: value?.date_to || null,
  }));
  const hasUnsavedFilterChanges = () => Boolean(definition) && filterStateFingerprint(definition) !== filterStateFingerprint(savedDashboardDefinition());
  const updateFilterActionState = () => {
    $('ds-save').disabled = !hasUnsavedFilterChanges() || filterActionBusy;
    $('ds-apply-filters').disabled = !definition || filterStateFingerprint(definition) === appliedFilterState || filterActionBusy;
  };
  const api = async (path = '', method = 'GET', body, signal) => {
    const response = await fetch(`/api/e2e-dashboards${path}`, {method, signal, cache: 'no-store', headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    const payload = await response.json();
    if (!response.ok) {
      const error = new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail));
      error.status = response.status;
      throw error;
    }
    return payload;
  };
  const safe = fn => async (...args) => { try { await fn(...args); } catch (error) { if (error.name !== 'AbortError') { status(error.message); if (window.showInfoDialog) window.showInfoDialog(error.message, {title:'E2E Dashboards',tone:'error'}); } } };
  const bind = (id, fn) => $(id).addEventListener('click', safe(fn));
  const setViewEnabled = enabled => { $('ds-view').disabled = !enabled; };
  const updateDirtyState = () => { dirty = hasUnsavedDashboardChanges(); updateFilterActionState(); return dirty; };
  const updateSavedDefinition = updates => {
    try {
      savedDefinition = definitionFingerprint({...JSON.parse(savedDefinition || '{}'), ...updates});
    } catch (_) {
      savedDefinition = definitionFingerprint(definition);
    }
    updateDirtyState();
  };
  const setPreparationState = state => {
    const notice = $('ds-preparing'), viewerNotice = $('ds-viewer-preparing');
    notice.hidden = state === 'hidden';
    viewerNotice.hidden = state !== 'preparing' || $('ds-viewer').hidden;
    if (state !== 'ready') { $('ds-preparing-rows').hidden = true; $('ds-preparing-rows').textContent = ''; }
    if (state === 'hidden') return;
    const ready = state === 'ready';
    const floatingFilters = $('ds-filter-panel').parentElement?.id === 'ds-filter-float';
    notice.dataset.state = state;
    $('ds-preparing-title').textContent = ready ? 'Dashboard is ready' : 'Dashboard is being prepared';
    $('ds-preparing-detail').textContent = floatingFilters
      ? (ready
        ? 'Data and filters are ready. The Dashboard is ready to use.'
        : 'Data and filters are still loading. The Dashboard will update when preparation is complete.')
      : (ready
        ? 'Data and filters are ready. You can now open View Dashboard.'
        : 'Data and filters are still loading. View Dashboard will become available when preparation is complete.');
  };
  function overlay(id, show) {
    const el = $(id);
    if (show) { focusReturn.set(id, document.activeElement); el.hidden = false; el.querySelector('[role=dialog]').focus(); }
    else { el.hidden = true; focusReturn.get(id)?.focus(); }
    if (id === 'ds-viewer') $('ds-viewer-preparing').hidden = !show || $('ds-preparing').dataset.state !== 'preparing';
    if (id === 'ds-viewer' && show) scheduleTemplateEditorPreload();
    document.body.style.overflow = [...document.querySelectorAll('.ds-overlay')].some(el => !el.hidden) ? 'hidden' : '';
  }
  function library() {
    rememberLibrary();
    $('ds-create').disabled = !$('ds-template').options.length;
    $('ds-count').textContent = `Total Dashboards: ${Object.keys(dashboards).length}`;
    const body = $('ds-dashboards-body'); body.replaceChildren();
    const rows = Object.entries(dashboards).sort(([, left], [, right]) => left.name.localeCompare(right.name));
    if (!rows.length) { const row = node('tr'), cell = node('td', 'No Dashboards have been created yet.', 'form-note'); cell.colSpan = 5; row.append(cell); body.append(row); return; }
    for (const [id, item] of rows) {
      const row = node('tr'); if (id === activeId) row.classList.add('ds-dashboard-active');
      const nameCell = node('td');
      const nameEditor = node('div', undefined, 'ds-dashboard-name-editor');
      const nameInput = document.createElement('input'); nameInput.type = 'text'; nameInput.value = item.name; nameInput.maxLength = 120; nameInput.setAttribute('aria-label', `Dashboard name: ${item.name}`);
      const nameSave = node('button', '✓', 'ds-dashboard-name-save'); nameSave.type = 'button'; nameSave.title = 'Save Dashboard name'; nameSave.setAttribute('aria-label', 'Save Dashboard name'); nameSave.hidden = true;
      const updateNameSave = () => { nameSave.hidden = nameInput.value.trim() === item.name; };
      nameInput.addEventListener('input', updateNameSave);
      nameInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); nameSave.click(); } });
      nameSave.onclick = safe(async () => {
        const name = nameInput.value.trim();
        if (!name || name === item.name) { nameInput.value = item.name; updateNameSave(); return; }
        const result = await api(`/${id}/name`, 'PATCH', {name});
        dashboards[id].name = result.name;
        if (id === activeId && definition) {
          definition.name = result.name; $('ds-name').value = result.name; $('ds-dashboard-name').textContent = `Dashboard Name: ${result.name}`;
          updateSavedDefinition({name: result.name});
          if (!$('ds-viewer').hidden) renderSlide();
        }
        library(); status(`Renamed Dashboard to “${result.name}”.`);
      });
      nameEditor.append(nameInput, nameSave); nameCell.append(nameEditor);
      row.append(nameCell, node('td', (item.technology || item.template_technology || 'nsa').toUpperCase()), node('td', item.template));
      const statusCell = node('td');
      const dashboardStatus = dashboardStatuses.get(id) || {state: 'checking', label: 'Checking'};
      const statusBadge = node('span', dashboardStatus.label, `ds-dashboard-status ds-dashboard-status-${dashboardStatus.state}`);
      statusBadge.dataset.dashboardStatusId = id;
      statusBadge.title = dashboardStatus.detail || dashboardStatus.label;
      statusCell.append(statusBadge); row.append(statusCell);
      const actions = node('div', undefined, 'ds-dashboard-actions');
      const action = (label, glyph, handler, tone = '') => {
        const button = node('button', glyph, `icon-action ds-dashboard-action ${tone}`); button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.onclick = safe(handler); actions.append(button);
      };
      action('View Dashboard', '◉', async () => {
        if (id !== activeId) {
          if (!await confirmDiscard()) return;
          const loading = openDashboard(id);
          overlay('ds-viewer', true);
          await loading;
        } else {
          overlay('ds-viewer', true);
          if (!prepared) await prepare();
          else renderSlide();
        }
      }, 'ds-dashboard-view');
      action(id === activeId ? 'Close Dashboard' : 'Open Dashboard', id === activeId ? '🚪' : '📂', async () => {
        if (id === activeId) { if (await confirmDiscard()) closeDashboard(); }
        else if (await confirmDiscard()) await openDashboard(id);
      }, id === activeId ? 'ds-dashboard-close' : 'ds-dashboard-open');
      action('Duplicate Dashboard', '⧉', async () => { if (await confirmDiscard()) await duplicateDashboard(id); });
      action('Export Dashboard', '↓', () => exportDashboard(item));
      action('Delete Dashboard', '×', async () => { await deleteDashboard(id); }, 'danger-button');
      const cell = node('td'); cell.append(actions); row.append(cell); body.append(row);
    }
  }
  const renderDashboardStatuses = () => {
    document.querySelectorAll('[data-dashboard-status-id]').forEach(badge => {
      const value = dashboardStatuses.get(badge.dataset.dashboardStatusId) || {state: 'checking', label: 'Checking'};
      badge.className = `ds-dashboard-status ds-dashboard-status-${value.state}`;
      badge.textContent = value.label;
      badge.title = value.detail || value.label;
    });
  };
  const setDashboardStatus = (id, state, label) => {
    if (!id) return;
    dashboardStatuses.set(id, {state, label});
    renderDashboardStatuses();
  };
  const refreshDashboardStatuses = async () => {
    if (dashboardStatusRefreshing) return;
    dashboardStatusRefreshing = true;
    try {
      const payload = await api('/statuses');
      for (const [id, value] of Object.entries(payload || {})) dashboardStatuses.set(id, value);
      for (const id of [...dashboardStatuses.keys()]) if (!dashboards[id]) dashboardStatuses.delete(id);
      renderDashboardStatuses();
    } catch (_error) { /* A status refresh must not interrupt Dashboard work. */ }
    finally { dashboardStatusRefreshing = false; }
  };
  function templateOptions(technology, selectedName = '') {
    const select = $('ds-template'), rows = config.templates[technology] || [];
    select.replaceChildren(...rows.map(row => option(row.identifier, row.name)));
    const selected = rows.find(row => row.name === selectedName) || rows[0];
    select.value = selected?.identifier || '';
    return selected;
  }
  templateOptions($('ds-nr-mode').value);
  function setTemplate(value) {
    const technology = $('ds-nr-mode').value;
    const selected = (config.templates[technology] || []).find(row => row.identifier === value);
    if (!selected || !definition) return;
    definition.template_technology = technology; definition.technology = technology; definition.template = selected.name;
  }
  function setNrMode(technology, selectedName = '') {
    const normalized = config.templates[technology] ? technology : 'nsa';
    $('ds-nr-mode').value = normalized;
    return templateOptions(normalized, selectedName);
  }
  function selectControl(label, values, selected, change, multiple = false, isUnsaved = () => false) {
    const host = node('label', label, 'ds-source-filter'), select = document.createElement('select');
    const updateUnsavedState = () => host.classList.toggle('ds-filter-unsaved', isUnsaved());
    select.multiple = multiple; if (multiple) { select.size = Math.max(2, Math.min(4, values.length)); select.dataset.multiselectAutoClose = '1000'; }
    if (!values.length) { select.disabled = true; select.multiple = false; select.size = 1; select.append(option('', 'No datasets available')); }
    for (const [value, text] of values) { const opt = option(value, text); opt.selected = multiple ? selected.map(String).includes(String(value)) : value === selected; select.append(opt); }
    updateUnsavedState();
    select.addEventListener('change', () => { change(multiple ? [...select.selectedOptions].map(opt => opt.value) : select.value); updateUnsavedState(); filterChanged(); });
    host.append(select); return host;
  }
  function applyDateBounds(bounds) {
    const minimum = /^\d{4}-\d{2}-\d{2}$/.test(String(bounds?.min || '')) ? bounds.min : '';
    const maximum = /^\d{4}-\d{2}-\d{2}$/.test(String(bounds?.max || '')) ? bounds.max : '';
    const previous = dateBounds;
    dateBounds = minimum && maximum && minimum <= maximum ? {min: minimum, max: maximum} : null;
    if (!dateBounds || !definition) return previous !== dateBounds;
    const from = definition.date_from;
    const to = definition.date_to;
    definition.date_from = !from || from < dateBounds.min || from > dateBounds.max ? dateBounds.min : from;
    definition.date_to = !to || to < dateBounds.min || to > dateBounds.max ? dateBounds.max : to;
    return previous?.min !== dateBounds.min || previous?.max !== dateBounds.max || from !== definition.date_from || to !== definition.date_to;
  }
  const parseCalendarDate = value => /^\d{4}-\d{2}-\d{2}$/.test(String(value || '')) ? new Date(`${value}T00:00:00`) : null;
  const calendarDateValue = value => [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-');
  const calendarMonthValue = value => value.getFullYear() * 12 + value.getMonth();
  function datePicker(key, label) {
    const wrapper = node('div', undefined, 'ds-date-picker');
    wrapper.classList.toggle('ds-date-picker-unsaved', hasUnsavedDate(key));
    const captionLabel = node('span', label, 'ds-date-picker-label');
    const input = document.createElement('input');
    input.type = 'text'; input.readOnly = true; input.value = definition[key] || ''; input.placeholder = 'Select date'; input.setAttribute('aria-label', label);
    const menu = node('div', undefined, 'ds-date-picker-menu'); menu.hidden = true; menu.setAttribute('role', 'dialog'); menu.setAttribute('aria-label', `${label} calendar`);
    const header = node('div', undefined, 'ds-date-picker-header');
    const previous = node('button', '‹', 'ds-date-picker-nav'); previous.type = 'button'; previous.setAttribute('aria-label', 'Previous month');
    const caption = node('strong');
    const next = node('button', '›', 'ds-date-picker-nav'); next.type = 'button'; next.setAttribute('aria-label', 'Next month');
    header.append(previous, caption, next);
    const weekdays = node('div', undefined, 'ds-date-picker-weekdays'); ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach(day => weekdays.append(node('span', day)));
    const days = node('div', undefined, 'ds-date-picker-days'); menu.append(header, weekdays, days);
    const minimum = parseCalendarDate(dateBounds?.min);
    const maximum = parseCalendarDate(dateBounds?.max);
    let month = parseCalendarDate(definition[key]) || minimum || new Date(); month.setDate(1);
    const render = () => {
      caption.textContent = month.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
      previous.disabled = Boolean(minimum && calendarMonthValue(month) <= calendarMonthValue(minimum));
      next.disabled = Boolean(maximum && calendarMonthValue(month) >= calendarMonthValue(maximum));
      days.replaceChildren();
      const offset = (month.getDay() + 6) % 7;
      for (let index = 0; index < offset; index += 1) days.append(node('span', '', 'ds-date-picker-blank'));
      const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
      for (let day = 1; day <= count; day += 1) {
        const value = new Date(month.getFullYear(), month.getMonth(), day);
        const iso = calendarDateValue(value);
        const button = node('button', String(day), 'ds-date-picker-day'); button.type = 'button'; button.disabled = Boolean((minimum && value < minimum) || (maximum && value > maximum));
        button.classList.toggle('is-selected', input.value === iso);
        button.addEventListener('click', () => { input.value = iso; definition[key] = iso; wrapper.classList.toggle('ds-date-picker-unsaved', hasUnsavedDate(key)); menu.hidden = true; filterChanged(); });
        days.append(button);
      }
    };
    previous.addEventListener('click', () => { month.setMonth(month.getMonth() - 1); render(); });
    next.addEventListener('click', () => { month.setMonth(month.getMonth() + 1); render(); });
    input.addEventListener('click', () => { menu.hidden = !menu.hidden; if (!menu.hidden) render(); });
    input.addEventListener('keydown', event => { if (event.key === 'Escape') menu.hidden = true; else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); menu.hidden = !menu.hidden; if (!menu.hidden) render(); } });
    document.addEventListener('pointerdown', event => { if (!wrapper.contains(event.target)) menu.hidden = true; });
    wrapper.append(captionLabel, input, menu); return wrapper;
  }
  function sources() {
    const host = $('ds-sources'); host.replaceChildren();
    for (const kind of ['data','voice','speech']) host.append(selectControl(`CDR ${kind[0].toUpperCase()+kind.slice(1)}`, config.datasets[kind].map(row => [String(row.id), `${row.file_name} · ${row.row_count} rows`]), definition.datasets[kind] || [], values => { definition.datasets[kind] = values.map(Number); }, true, () => hasUnsavedSource(kind)));
    host.append(selectControl('Scope', [['single','Operator Comparison'],['multivendor','Multivendor Comparison']], definition.scope, value => { definition.scope = value; }, false, hasUnsavedScope));
    for (const [key, label] of [['date_from', 'Date from'], ['date_to', 'Date to']]) host.append(datePicker(key, label));
    globalThis.setupCustomMultiSelects?.();
  }
  function facets() {
    const defaultHost = $('ds-default-facets'), additionalHost = $('ds-additional-facets'); defaultHost.replaceChildren(); additionalHost.replaceChildren();
    definition.hidden_filters ||= [];
    const hidden = new Set(definition.hidden_filters.map(identity));
    const fields = new Set([...facetFields.filter(field => !hidden.has(identity(field))), ...Object.keys(definition.filters), ...definition.custom_fields]);
    for (const field of fields) {
      const facet = node('div', undefined, 'ds-facet');
      facet.classList.toggle('ds-filter-unsaved', hasUnsavedFilter(field));
      const selected = definition.filters[field];
      const custom = definition.custom_fields.includes(field);
      const label = custom ? field : field === 'technology_primary' ? 'Technology' : field.replaceAll('_',' ').replace(/\b\w/g, letter => letter.toUpperCase());
      const head = node('div', undefined, 'ds-facet-head'); head.append(node('span', label));
      const remove = node('button', '×', 'ds-facet-remove'); remove.type = 'button'; remove.title = `Remove ${label} filter`; remove.setAttribute('aria-label', `Remove ${label} filter`);
      remove.onclick = safe(async () => {
        const confirmed = await window.showConfirmDialog(`Remove the ${label} filter?`, {title: 'Remove filter', confirmLabel: 'Remove', tone: 'danger'});
        if (!confirmed) return;
        if (custom) definition.custom_fields = definition.custom_fields.filter(item => item !== field);
        else if (!definition.hidden_filters.some(item => identity(item) === identity(field))) definition.hidden_filters.push(field);
        delete definition.filters[field]; facets(); filterChanged();
      });
      head.append(remove); facet.append(head);
      const values = document.createElement('select'); values.multiple = true; values.size = 1; values.dataset.multiselectAutoClose = '1000'; values.setAttribute('aria-label', `${label} filter`);
      const available = [...new Set([...(facetOptions[field] || []), ...(selected || [])])];
      for (const value of available) {
        const item = option(value, value || '(Empty)'); item.selected = !selected || selected.includes(value); values.append(item);
      }
      if (!available.length) { values.disabled = true; values.append(option('', facetsLoading ? 'Loading values…' : 'No matching values')); }
      values.onchange = () => {
        const next = [...values.selectedOptions].map(item => item.value).filter(Boolean);
        const current = (selected || available).filter(Boolean);
        if (next.length === current.length && next.every(value => current.includes(value))) return;
        definition.filters[field] = next;
        facet.classList.toggle('ds-filter-unsaved', hasUnsavedFilter(field));
        filterChanged();
      };
      facet.append(values);
      (custom ? additionalHost : defaultHost).append(facet);
    }
    if (!additionalHost.childElementCount) additionalHost.append(node('p', 'No additional filters have been added.', 'form-note ds-no-additional-filters'));
    const visible = [...fields].map(field => identity(field));
    const restorable = facetFields.filter(field => hidden.has(identity(field)));
    const choices = [...restorable, ...availableFields].filter((field, index, all) => !visible.includes(identity(field)) && all.findIndex(item => identity(item) === identity(field)) === index);
    const fieldPicker = $('ds-custom-field');
    const previous = fieldPicker.value;
    fieldPicker.replaceChildren(...choices.map(field => option(field, field)));
    fieldPicker.disabled = choices.length === 0;
    $('ds-add-filter').disabled = choices.length === 0;
    if ([...fieldPicker.options].some(item => item.value === previous)) fieldPicker.value = previous;
    fieldPicker.dispatchEvent(new Event('multiselect:options-updated'));
    globalThis.setupCustomMultiSelects?.();
  }
  const hasOpenFacetMenu = () => Boolean($('ds-filter-panel').querySelector('.multiselect-menu:not([hidden])'));
  function refreshFacetsAfterMenusClose() {
    clearTimeout(facetsRefreshTimer);
    if (!hasOpenFacetMenu()) { facets(); return; }
    facetsRefreshTimer = setTimeout(refreshFacetsAfterMenusClose, 100);
  }
  const rememberPrepared = payload => {
    const fingerprint = definitionFingerprint(definition);
    preparedPayloads.set(activeId, {payload, fingerprint});
    try { sessionStorage.setItem(preparedStorageKey, JSON.stringify({dashboardId: activeId, token: payload.token, fingerprint})); }
    catch (_) { /* Session storage is optional. */ }
  };
  const forgetPrepared = () => {
    preparedPayloads.delete(activeId);
    try { sessionStorage.removeItem(preparedStorageKey); } catch (_) { /* Session storage is optional. */ }
  };
  const applyPreparedPayload = payload => {
    prepared = payload; facetOptions = payload.options; facetFields = payload.filter_fields || facetFields; availableFields = payload.available_fields || payload.custom_fields || []; const datesChanged = applyDateBounds(payload.date_bounds); if (datesChanged) sources(); facetsLoading = false;
    appliedFilterState = filterStateFingerprint(definition);
    if (hasOpenFacetMenu()) refreshFacetsAfterMenusClose(); else facets();
    setViewEnabled(Boolean(payload.slides?.length));
    const rowLabel = payload.rows_exact === false ? 'source rows' : 'rows';
    $('ds-preparing-rows').textContent = Object.entries(payload.rows).map(([kind,count]) => `${kind.toUpperCase()}: ${count.toLocaleString()} ${rowLabel}`).join(' · ');
    $('ds-preparing-rows').hidden = !$('ds-preparing-rows').textContent;
    setPreparationState('ready');
    chartPayloads.clear(); renderedChartPayloads.clear(); rememberPrepared(payload);
    if (!$('ds-viewer').hidden) renderSlide();
  };
  async function restorePrepared(id) {
    const inMemory = preparedPayloads.get(id);
    const fingerprint = definitionFingerprint(definition);
    if (inMemory?.fingerprint === fingerprint) { applyPreparedPayload(inMemory.payload); return true; }
    let cached;
    try { cached = JSON.parse(sessionStorage.getItem(preparedStorageKey) || 'null'); }
    catch (_) { return false; }
    if (cached?.dashboardId === id && cached.token && cached.fingerprint === fingerprint) {
      try { applyPreparedPayload(await api(`/prepared/${encodeURIComponent(cached.token)}`)); return true; }
      catch (error) { if (error.message.includes('expired')) forgetPrepared(); }
    }
    for (let attempt = 0; attempt < 480 && activeId === id; attempt += 1) {
      try {
        applyPreparedPayload(await api(`/prefetched/${encodeURIComponent(id)}`));
        return true;
      } catch (error) {
        if (error.status !== 409) return false;
        if (attempt === 0) setPreparationState('preparing');
        await new Promise(resolve => setTimeout(resolve, 250));
      }
    }
    return false;
  }
  function filterChanged() {
    updateDirtyState();
    status('Filter changes are ready to apply.');
  }
  function changed() {
    dismissPreparationStatus(); forgetPrepared();
    updateDirtyState(); prepared = null; appliedFilterState = ''; ++sequence; controller?.abort(); preparing = null;
    setViewEnabled(false);
    setPreparationState('preparing');
    $('ds-rows').textContent = '';
    if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div','Updating dashboards…','ds-empty'));
    const delay = $('ds-filter-overlay').hidden ? 350 : 120;
    clearTimeout(timer); timer = setTimeout(safe(prepare), delay);
  }
  async function prepare() {
    if (preparing) return preparing;
    const pending = (async () => {
    clearTimeout(timer); const current = ++sequence; controller?.abort(); controller = new AbortController();
    dismissPreparationStatus(); backgroundPreparationToken = `prepare-${current}`;
    emitPreparationStatus('processing', 'Building the filtered Dashboard selection');
    setDashboardStatus(activeId, 'loading-data', 'Loading data');
    filterActionBusy = true; updateFilterActionState();
    facetsLoading = true;
    if (!hasOpenFacetMenu()) facets();
    setViewEnabled(false);
    setPreparationState('preparing');
    $('ds-rows').textContent = '';
    try {
      const payload = await api(`/prepare${activeId ? `?dashboard_id=${encodeURIComponent(activeId)}` : ''}`,'POST',definition,controller.signal);
      if (current !== sequence) return;
      applyPreparedPayload(payload);
      window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));
    } catch (error) { if (current === sequence && error.name !== 'AbortError') { setDashboardStatus(activeId, 'error', 'Error'); facetsLoading = false; facets(); setViewEnabled(false); setPreparationState('hidden'); $('ds-rows').textContent = error.message; if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div',error.message,'ds-empty')); } throw error; }
    })();
    preparing = pending;
    try { return await pending; }
    finally {
      dismissPreparationStatus();
      if (preparing === pending) preparing = null;
      filterActionBusy = false; updateFilterActionState();
    }
  }
  async function openDashboard(id) {
    clearTimeout(facetsRefreshTimer);
    dismissPreparationStatus();
    clearTimeout(timer); ++sequence; controller?.abort(); preparing = null;
    stopPresentation();
    activeId = id; definition = canonicalDashboardDefinition(dashboards[id]); savedDefinition = definitionFingerprint(definition); dirty = false; prepared = null; appliedFilterState = ''; facetOptions = {}; availableFields = []; slideIndex = 0; setViewEnabled(false); rememberOpen(id);
    resetViewerForDashboard();
    $('ds-name').value = definition.name; setNrMode(definition.technology || definition.template_technology, definition.template);
    $('ds-filter-panel').hidden = false; $('ds-dashboard-name').textContent = `Dashboard Name: ${definition.name}`; sources(); facets(); library(); status(''); if (!await restorePrepared(id)) await prepare();
    // UI setup may fill omitted legacy defaults. Treat that normalization as the
    // persisted baseline, so opening another Dashboard does not prompt to discard it.
    savedDefinition = definitionFingerprint(definition); updateDirtyState();
    // Date defaults may be derived while the prepared payload is restored. Rebuild
    // the controls after making them the saved baseline so their amber state agrees
    // with the disabled Apply and Save buttons.
    sources(); facets();
  }
  async function save() {
    if (!activeId || !definition || !hasUnsavedFilterChanges()) return;
    filterActionBusy = true; updateFilterActionState();
    try {
      const dashboardId = activeId, item = definition;
      item.name = $('ds-name').value.trim(); const result = await api(`/${dashboardId}`,'PUT',item);
      if (dashboardId !== activeId || item !== definition) return;
      definition = canonicalDashboardDefinition(result.definition); dashboards[dashboardId] = structuredClone(definition); savedDefinition = definitionFingerprint(definition); updateDirtyState(); sources(); facets(); library();
      await prepare();
      status(`Saved filters for “${definition.name}”.`);
    } finally {
      filterActionBusy = false; updateFilterActionState();
    }
  }
  const confirmDiscard = async (ignoredFields = []) => !hasUnsavedDashboardChanges(ignoredFields) || await window.showConfirmDialog('Discard unsaved Dashboard changes?', {title:'Unsaved changes',confirmLabel:'Discard'});
  bind('ds-create', async () => {
    if (!await confirmDiscard(['name', 'template', 'template_technology', 'technology'])) return;
    const technology = $('ds-nr-mode').value;
    const selected = (config.templates[technology] || []).find(row => row.identifier === $('ds-template').value);
    if (!selected) throw new Error('Choose a template for the selected NR Mode.');
    const item = {name:$('ds-name').value.trim(),template_technology:technology,template:selected.name,technology,scope:'single',datasets:Object.fromEntries(Object.entries(config.datasets).map(([kind,rows])=>[kind,rows.map(row=>row.id)])),filters:{},custom_fields:[],date_from:null,date_to:null};
    status(`Creating “${item.name}”…`); $('ds-create').disabled = true;
    try { const id = dashboardId(), result = await api(`/${id}`,'PUT',item); dashboards[id] = result.definition; await openDashboard(id); }
    finally { $('ds-create').disabled = !$('ds-template').options.length; }
  });
  bind('ds-save', save);
  bind('ds-apply-filters', async () => { if (definition && filterStateFingerprint(definition) !== appliedFilterState) await prepare(); });
  async function duplicateDashboard(sourceId) {
    const id = dashboardId(), item = structuredClone(dashboards[sourceId]); item.name = nextName(`${item.name.slice(0,110)} (copy)`);
    status(`Duplicating “${dashboards[sourceId].name}”…`);
    const result = await api(`/${id}`,'PUT',item); dashboards[id] = result.definition; await openDashboard(id);
  }
  function exportDashboard(item) { const blob = new Blob([JSON.stringify({format:'dashboard-analytic-dashboard',version:2,definition:item},null,2)],{type:'application/json'}); const url = URL.createObjectURL(blob), a = node('a'); a.href = url; a.download = `${item.name.replace(/[^a-z0-9_-]/gi,'_')}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); status(`Exported “${item.name}”.`); }
  async function deleteDashboard(id) {
    const item = dashboards[id]; if (!item || !await window.showConfirmDialog(`Delete “${item.name}”?`,{title:'Delete Dashboard',confirmLabel:'Delete',tone:'danger'})) return;
    if (id === activeId && !await confirmDiscard()) return;
    status(`Deleting “${item.name}”…`);
    await api(`/${id}`,'DELETE'); delete dashboards[id]; dashboardStatuses.delete(id); if (id === activeId) closeDashboard(); else { library(); status(`Deleted “${item.name}”.`); }
  }
  bind('ds-import',() => $('ds-import-file').click());
  $('ds-import-file').onchange = safe(async () => { const file = $('ds-import-file').files[0]; if (!file) return; const payload = JSON.parse(await file.text()); const legacy = payload.format === 'dashboard-analytic-dashboard-set' && payload.version === 1; if (!legacy && (payload.format !== 'dashboard-analytic-dashboard' || payload.version !== 2)) throw new Error('Unsupported Dashboard file.'); if (!await confirmDiscard()) return; payload.definition.name = nextName(payload.definition.name); const id = dashboardId(), result = await api(`/${id}`,'PUT',payload.definition); dashboards[id] = result.definition; await openDashboard(id); $('ds-import-file').value = ''; });
  function closeDashboard() { clearTimeout(facetsRefreshTimer); dismissPreparationStatus(); stopPresentation(); rememberOpen(''); ++sequence; clearTimeout(timer); controller?.abort(); preparing = null; activeId = ''; definition = null; savedDefinition = ''; appliedFilterState = ''; prepared = null; dirty = false; setViewEnabled(false); setPreparationState('hidden'); $('ds-filter-panel').hidden = true; $('ds-dashboard-name').textContent = 'Dashboard Name: —'; $('ds-name').value = ''; setNrMode('nsa'); library(); status('Dashboard closed.'); }
  $('ds-name').oninput = () => { if (definition) { definition.name = $('ds-name').value; updateDirtyState(); } };
  $('ds-nr-mode').onchange = () => {
    const selected = setNrMode($('ds-nr-mode').value);
    if (definition && selected) { definition.template_technology = definition.technology = $('ds-nr-mode').value; definition.template = selected.name; changed(); }
  };
  $('ds-template').onchange = () => { if (definition) { setTemplate($('ds-template').value); changed(); } };
  bind('ds-add-filter',() => { const field = $('ds-custom-field').value; if (!field) return; const defaultField = facetFields.find(item => identity(item) === identity(field)); if (defaultField) definition.hidden_filters = definition.hidden_filters.filter(item => identity(item) !== identity(defaultField)); else definition.custom_fields.push(field); facets(); filterChanged(); });
  bind('ds-clear-filters', () => { definition.filters = {}; definition.date_from = definition.date_to = null; sources(); facets(); filterChanged(); });
  bind('ds-last-saved-filters', () => {
    const saved = savedDashboardDefinition();
    const current = JSON.stringify({datasets: definition.datasets, scope: definition.scope, filters: definition.filters, custom_fields: definition.custom_fields, hidden_filters: definition.hidden_filters, date_from: definition.date_from, date_to: definition.date_to});
    definition.datasets = structuredClone(saved.datasets || {});
    definition.scope = saved.scope || 'single';
    definition.filters = structuredClone(saved.filters || {});
    definition.custom_fields = structuredClone(saved.custom_fields || []);
    definition.hidden_filters = structuredClone(saved.hidden_filters || []);
    definition.date_from = saved.date_from || null;
    definition.date_to = saved.date_to || null;
    applyDateBounds(dateBounds);
    const restored = JSON.stringify({datasets: definition.datasets, scope: definition.scope, filters: definition.filters, custom_fields: definition.custom_fields, hidden_filters: definition.hidden_filters, date_from: definition.date_from, date_to: definition.date_to});
    if (restored === current) return;
    sources(); facets(); filterChanged();
  });
  bind('ds-viewer-refresh',prepare);
  bind('ds-view',async () => {
    if (!prepared?.slides.length) return;
    setViewEnabled(false);
    try {
      overlay('ds-viewer', true); renderSlide();
    } finally {
      setViewEnabled(Boolean(prepared?.slides.length));
    }
  });
  function loadChartPayload(chart, priority = 'high') {
    const url = `/api/e2e-dashboards/chart/${prepared.token}/${chart.index}`;
    const rendered = renderedChartPayloads.get(url);
    if (rendered) return Promise.resolve(rendered);
    let request = chartPayloads.get(url);
    if (!request) {
      request = fetch(url, {cache: 'no-store', credentials: 'same-origin', priority}).then(async response => {
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
          if (response.redirected || response.url.includes('/login')) throw new Error('Your session has expired. Please sign in again.');
          throw new Error('The chart service returned an invalid response.');
        }
        const payload = await response.json();
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Unable to prepare chart data.');
        renderedChartPayloads.set(url, payload);
        while (renderedChartPayloads.size > 160) renderedChartPayloads.delete(renderedChartPayloads.keys().next().value);
        return payload;
      });
      chartPayloads.set(url, request);
      while (chartPayloads.size > 160) chartPayloads.delete(chartPayloads.keys().next().value);
      request.catch(() => { if (chartPayloads.get(url) === request) chartPayloads.delete(url); });
    }
    return request;
  }
  function structuralDashboard(stage, slide) {
    const kind = String(slide.structural_type || '').toLowerCase().includes('transition') ? 'transition' : 'title';
    const cover = node('section', undefined, `ds-structural-slide ds-structural-${kind}`);
    cover.setAttribute('aria-label', `${kind === 'transition' ? 'Transition' : 'Title'} dashboard: ${slide.title || 'Untitled'}`);
    const brand = node('div', undefined, 'ds-structural-brand');
    const mark = document.createElement('img'); mark.src = config.brand_mark; mark.alt = `${config.app_name || 'Dashboard Analytic'} logo`; mark.width = 72; mark.height = 72;
    brand.append(node('strong', config.app_name || 'Dashboard Analytic'), mark);
    const content = node('div', undefined, 'ds-structural-content');
    content.append(node('h3', slide.title || 'Dashboard', 'ds-structural-title'));
    if (slide.subtitle) content.append(node('p', slide.subtitle, 'ds-structural-subtitle'));
    cover.append(content, brand); stage.append(cover);
  }
  function chartZoomControls(canvas) {
    const controls = node('div', undefined, 'ds-chart-zoom'); controls.hidden = true; controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', 'Chart zoom');
    const zoomOut = node('button', '−', 'ds-chart-zoom-button'); zoomOut.type = 'button'; zoomOut.title = 'Zoom out'; zoomOut.setAttribute('aria-label', 'Zoom out');
    const level = node('output', '100%', 'ds-chart-zoom-level'); level.setAttribute('aria-label', 'Current zoom');
    const zoomIn = node('button', '+', 'ds-chart-zoom-button'); zoomIn.type = 'button'; zoomIn.title = 'Zoom in'; zoomIn.setAttribute('aria-label', 'Zoom in');
    const reset = node('button', '↺', 'ds-chart-zoom-button ds-chart-zoom-reset'); reset.type = 'button'; reset.title = 'Reset zoom'; reset.setAttribute('aria-label', 'Reset zoom');
    const sync = zoom => {
      const value = Math.max(1, Math.min(4, Number(zoom) || 1));
      level.value = `${Math.round(value * 100)}%`; level.textContent = level.value;
      zoomOut.disabled = value <= 1; reset.disabled = value <= 1; zoomIn.disabled = value >= 4;
    };
    const apply = zoom => { if (globalThis.setDashboardChartZoom) sync(globalThis.setDashboardChartZoom(canvas, zoom)); };
    zoomOut.onclick = event => { event.stopPropagation(); apply((globalThis.getDashboardChartZoom?.(canvas) || 1) - .25); };
    zoomIn.onclick = event => { event.stopPropagation(); apply((globalThis.getDashboardChartZoom?.(canvas) || 1) + .25); };
    reset.onclick = event => { event.stopPropagation(); apply(1); };
    canvas.addEventListener('dashboardchartzoom', event => sync(event.detail?.zoom));
    controls.reset = () => apply(1);
    sync(1); controls.append(zoomOut, level, zoomIn, reset); return controls;
  }
  const expandedZoom = chartZoomControls($('ds-chart-expanded-canvas'));
  $('ds-chart-expanded-zoom').append(expandedZoom);
  const expandedCanvasShell = $('ds-chart-expanded-canvas-shell');
  let expandedControlsTimer;
  const showExpandedCanvasControls = () => {
    clearTimeout(expandedControlsTimer);
    expandedControlsTimer = null;
    expandedCanvasShell.classList.add('ds-hover');
  };
  const hideExpandedCanvasControls = () => {
    if (expandedControlsTimer) return;
    expandedControlsTimer = setTimeout(() => {
      expandedCanvasShell.classList.remove('ds-hover');
      expandedControlsTimer = null;
    }, 500);
  };
  expandedCanvasShell.onpointerenter = showExpandedCanvasControls;
  expandedCanvasShell.onpointerleave = hideExpandedCanvasControls;
  expandedCanvasShell.onfocusin = showExpandedCanvasControls;
  expandedCanvasShell.onfocusout = () => { if (!expandedCanvasShell.contains(document.activeElement)) hideExpandedCanvasControls(); };
  let expandedChart = null;
  async function openChartDataset(chart) {
    dataIndex = chart.index; dataPage = 0; dataToken = prepared.token; dataPages.clear();
    overlay('ds-data-overlay', true); await renderData();
  }
  $('ds-chart-expanded-data').onclick = safe(async () => { if (expandedChart) await openChartDataset(expandedChart); });
  const expandedCharts = () => prepared?.slides.flatMap(slide => slide.charts).filter(chart => chart.available) || [];
  const syncExpandedChartNavigation = () => {
    const charts = expandedCharts();
    const index = charts.findIndex(chart => chart.index === expandedChart?.index);
    $('ds-chart-expanded-position').textContent = index < 0 ? 'Chart —' : `Chart ${index + 1} / ${charts.length}`;
    $('ds-chart-expanded-first').disabled = $('ds-chart-expanded-prev').disabled = index <= 0;
    $('ds-chart-expanded-next').disabled = $('ds-chart-expanded-last').disabled = index < 0 || index >= charts.length - 1;
  };
  const navigateExpandedChart = async target => {
    const charts = expandedCharts();
    const current = charts.findIndex(chart => chart.index === expandedChart?.index);
    if (current < 0 || target < 0 || target >= charts.length || target === current) return;
    await openExpandedChart(charts[target]);
  };
  $('ds-chart-expanded-first').onclick = safe(async () => navigateExpandedChart(0));
  $('ds-chart-expanded-prev').onclick = safe(async () => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) - 1));
  $('ds-chart-expanded-next').onclick = safe(async () => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) + 1));
  $('ds-chart-expanded-last').onclick = safe(async () => navigateExpandedChart(expandedCharts().length - 1));
  const openFloatingFilters = () => { $('ds-filter-float').append($('ds-filter-panel')); setPreparationState($('ds-preparing').dataset.state || 'hidden'); $('ds-view').hidden = true; $('ds-filter-close-action').hidden = false; overlay('ds-filter-overlay', true); };
  const closeFilters = async () => {
    if (hasUnsavedDashboardChanges() && !await window.showConfirmDialog(
      'This Dashboard has unsaved changes. Close Adaptative Filters without saving them?',
      {title: 'Unsaved Dashboard changes', confirmLabel: 'Close filters', cancelLabel: 'Keep editing', tone: 'warning'},
    )) return false;
    $('ds-filter-home').append($('ds-filter-panel')); setPreparationState($('ds-preparing').dataset.state || 'hidden'); $('ds-view').hidden = false; $('ds-filter-close-action').hidden = true; overlay('ds-filter-overlay', false);
    return true;
  };
  const templateEditorHasUnsavedChanges = () => {
    try {
      return Boolean($('ds-editor-frame').contentDocument?.querySelector('[data-catalogue-editor]')?.hasUnsavedCatalogueChanges?.());
    } catch (_error) {
      return false;
    }
  };
  const templateEditorBaseUrl = () => definition
    ? `/admin/report-templates/${encodeURIComponent(definition.template_technology)}/${encodeURIComponent(definition.template)}/editor`
    : '';
  const focusTemplateEditorRow = row => {
    const frame = $('ds-editor-frame');
    frame.dataset.editorFocusRow = String(row);
    if (frame.contentDocument?.readyState === 'complete') {
      frame.contentWindow?.postMessage({type: 'dashboard-analytic:focus-template-row', row}, window.location.origin);
    }
  };
  function scheduleTemplateEditorPreload() {
    clearTimeout(templateEditorPreloadTimer);
    templateEditorPreloadTimer = window.setTimeout(() => {
      if ($('ds-viewer').hidden || !definition) return;
      const frame = $('ds-editor-frame');
      const url = templateEditorBaseUrl();
      if (url && frame.dataset.editorUrl !== url) {
        frame.dataset.editorUrl = url;
        frame.removeAttribute('data-editor-focus-row');
        frame.src = url;
      }
    }, 250);
  }
  $('ds-editor-frame').addEventListener('load', () => {
    const row = Number($('ds-editor-frame').dataset.editorFocusRow);
    if (Number.isInteger(row) && row >= 0) focusTemplateEditorRow(row);
  });
  const closeTemplateEditor = async () => {
    const hasUnsavedChanges = templateEditorHasUnsavedChanges();
    if (hasUnsavedChanges && !await window.showConfirmDialog(
      'This Report Template has unsaved changes. Close the editor without saving them?',
      {title: 'Unsaved Report Template changes', confirmLabel: 'Close editor', cancelLabel: 'Keep editing', tone: 'warning'},
    )) return false;
    const templateChanged = templateEditorSaved;
    // Keep the already initialized editor alive. Recreating its iframe makes
    // every reopening parse the template and rebuild the complete table.
    overlay('ds-editor-overlay', false); templateEditorSaved = false;
    if (templateChanged) await prepare();
    return true;
  };
  const openTemplateEditor = focusRow => {
    if (!definition || !Number.isInteger(focusRow)) return;
    templateEditorSaved = false;
    const frame = $('ds-editor-frame');
    const url = templateEditorBaseUrl();
    if (frame.dataset.editorUrl === url) {
      focusTemplateEditorRow(focusRow);
    } else {
      frame.dataset.editorUrl = url;
      frame.dataset.editorFocusRow = String(focusRow);
      frame.src = `${url}?focus_row=${focusRow}`;
    }
    overlay('ds-editor-overlay', true);
  };
  $('ds-chart-expanded-refresh').onclick = safe(prepare);
  $('ds-chart-expanded-filters').onclick = openFloatingFilters;
  $('ds-chart-expanded-auto-fields')?.addEventListener('click', () => document.querySelector('.ds-viewer-panel [data-workspace-manage-calculated-dimensions]')?.click());
  $('ds-chart-expanded-edit')?.addEventListener('click', () => openTemplateEditor(expandedChart?.focus_row));
  function expandedChartOverlay(show) {
    const overlay = $('ds-chart-expanded-overlay');
    if (show) {
      focusReturn.set('ds-chart-expanded-overlay', document.activeElement);
      overlay.hidden = false;
      overlay.querySelector('[role=dialog]').focus();
    } else {
      expandedChartRequest += 1;
      expandedChart = null;
      overlay.hidden = true;
      $('ds-chart-expanded-canvas').hidden = true;
      focusReturn.get('ds-chart-expanded-overlay')?.focus();
    }
  }
  $('ds-chart-expanded-overlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) expandedChartOverlay(false);
  });
  async function openExpandedChart(chart, renderedPayload = null) {
    stopPresentation();
    const request = ++expandedChartRequest;
    const token = prepared?.token;
    const canvas = $('ds-chart-expanded-canvas');
    const message = $('ds-chart-expanded-message');
    expandedChart = chart;
    syncExpandedChartNavigation();
    if ($('ds-chart-expanded-edit')) $('ds-chart-expanded-edit').disabled = !Number.isInteger(chart.focus_row);
    expandedZoom.reset(); expandedZoom.hidden = true;
    const initialTitle = renderedPayload?.title || chart.title || 'Expanded chart';
    $('ds-chart-expanded-title').textContent = initialTitle;
    canvas.setAttribute('aria-label', initialTitle);
    canvas.hidden = true;
    message.hidden = false;
    message.textContent = `Loading ${chart.title || 'chart'}…`;
    expandedChartOverlay(true);
    let payload;
    try {
      payload = renderedPayload || await loadChartPayload(chart);
    } catch (error) {
      if (request === expandedChartRequest && !$('ds-chart-expanded-overlay').hidden) message.textContent = error.message || `Unable to load ${chart.title || 'chart'}.`;
      throw error;
    }
    if (request !== expandedChartRequest || token !== prepared?.token || $('ds-chart-expanded-overlay').hidden) return;
    const title = payload?.title || chart.title || 'Expanded chart';
    $('ds-chart-expanded-title').textContent = title;
    canvas.setAttribute('aria-label', title);
    canvas.hidden = false;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (request !== expandedChartRequest || token !== prepared?.token || $('ds-chart-expanded-overlay').hidden) return;
    try {
      globalThis.renderDashboardChart(canvas, payload);
      expandedZoom.hidden = false;
      message.hidden = true;
    } catch (error) {
      canvas.hidden = true;
      message.hidden = false;
      message.textContent = error.message || `Unable to render ${chart.title || 'chart'}.`;
      throw error;
    }
  }
  const currentSlideCommentKey = () => String(prepared?.slides[slideIndex]?.number ?? slideIndex + 1);
  function renderComments() {
    const list = $('ds-comments-list');
    if (!list || !definition) return;
    definition.slide_comments ||= {};
    const comments = definition.slide_comments[currentSlideCommentKey()] || [];
    list.replaceChildren();
    if (!comments.length) { list.append(node('li', 'No comments for this slide.', 'ds-comments-empty')); return; }
    comments.forEach((comment, index) => {
      const item = node('li', undefined, 'ds-comment');
      const editor = document.createElement('input'); editor.type = 'text'; editor.value = comment; editor.maxLength = 500; editor.setAttribute('aria-label', `Comment ${index + 1}`);
      let savedComment = comment;
      const saveEdit = safe(async () => {
        const value = editor.value.trim();
        if (value === savedComment || !definition) return;
        const slideComments = definition.slide_comments[currentSlideCommentKey()];
        if (!slideComments) return;
        slideComments[index] = value;
        await persistComments(); savedComment = value; renderComments();
      });
      editor.addEventListener('change', saveEdit);
      editor.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); editor.blur(); } });
      const remove = node('button', '×', 'ds-comment-remove'); remove.type = 'button'; remove.title = 'Remove comment'; remove.setAttribute('aria-label', 'Remove comment');
      remove.onclick = safe(async () => { definition.slide_comments[currentSlideCommentKey()].splice(index, 1); await persistComments(); renderComments(); });
      item.append(editor, remove); list.append(item);
    });
  }
  async function persistComments() {
    if (!activeId || !definition) return;
    const id = activeId;
    $('ds-comments-status').textContent = 'Saving…';
    const payload = await api(`/${id}/comments`, 'PATCH', {slide_comments: definition.slide_comments || {}});
    if (!definition || activeId !== id) return;
    definition.slide_comments = payload.slide_comments;
    updateSavedDefinition({slide_comments: payload.slide_comments});
    dashboards[id] = {...dashboards[id], slide_comments: structuredClone(payload.slide_comments)};
    $('ds-comments-status').textContent = 'Saved';
  }
  function syncPresentationControls() {
    const button = $('ds-presentation');
    button.classList.toggle('is-running', presentation.running);
    button.title = presentation.running ? 'Stop presentation' : 'Presentation';
    button.setAttribute('aria-label', presentation.running ? 'Stop presentation' : 'Presentation');
    $('ds-presentation-start').disabled = presentation.running;
    $('ds-presentation-stop').disabled = !presentation.running;
  }
  function stopPresentation() {
    clearTimeout(presentationTimer); presentationTimer = 0;
    if (!presentation.running) return;
    presentation.running = false; syncPresentationControls(); status('Presentation stopped.');
  }
  function schedulePresentationAdvance() {
    clearTimeout(presentationTimer);
    presentationTimer = setTimeout(() => {
      if (!presentation.running || !prepared) return;
      if (slideIndex >= prepared.slides.length - 1) { stopPresentation(); return; }
      slideIndex += 1; renderSlide(); schedulePresentationAdvance();
    }, presentation.delay);
  }
  function startPresentation() {
    if (!prepared?.slides.length) return;
    presentation.delay = Number($('ds-presentation-delay').value) * 1000;
    presentation.effect = $('ds-presentation-effect').value;
    presentation.running = true; syncPresentationControls(); overlay('ds-presentation-overlay', false); renderSlide(); schedulePresentationAdvance(); status(`Presentation started: ${presentation.delay / 1000} seconds per slide.`);
  }
  function resetViewerForDashboard() {
    // A new Dashboard can be opened while its server snapshot is still being
    // restored. Never leave the previous Dashboard's title, slide or comments
    // visible during that short wait.
    $('ds-position').textContent = definition ? `${definition.name} · Loading slides` : '';
    $('ds-title').textContent = 'Loading Dashboard…';
    $('ds-subtitle').textContent = '';
    $('ds-slide').replaceChildren(option('', 'Loading slides…'));
    $('ds-slide').disabled = true;
    $('ds-first').disabled = $('ds-prev').disabled = $('ds-next').disabled = $('ds-last').disabled = true;
    const stage = $('ds-charts');
    stage.classList.remove('ds-positioned', 'ds-structural-stage', 'ds-slide-transition');
    stage.replaceChildren(node('div', 'Loading available Dashboard charts…', 'ds-empty'));
    $('ds-comments-list').replaceChildren();
    $('ds-comments-status').textContent = '';
  }
  function renderSlide() {
    if (!prepared) return; slideIndex = Math.max(0,Math.min(slideIndex,prepared.slides.length-1));
    const slide = prepared.slides[slideIndex]; if (!slide) return;
    const visibleIndexes = slide.charts.filter(chart => chart.available).map(chart => chart.index);
    if (activeId && prepared.token && visibleIndexes.length) {
      void api(`/prefetched/${encodeURIComponent(activeId)}/priority`, 'POST', {token: prepared.token, indexes: visibleIndexes}).catch(() => undefined);
    }
    $('ds-title').textContent = slide.title || `Dashboard ${slide.number}`; $('ds-subtitle').textContent = slide.subtitle;
    $('ds-position').textContent = `${definition.name} · Slide ${slideIndex+1} / ${prepared.slides.length}`;
    $('ds-slide').replaceChildren(...prepared.slides.map((item,index)=>option(String(index),`${item.number} · ${item.title || 'Dashboard'}`))); $('ds-slide').disabled = false; $('ds-slide').value = String(slideIndex);
    $('ds-first').disabled = $('ds-prev').disabled = slideIndex === 0;
    $('ds-next').disabled = $('ds-last').disabled = slideIndex === prepared.slides.length - 1;
    $('ds-slide-content').classList.toggle('ds-comments-right', /\bcomments\s+right\b/i.test(slide.layout || ''));
    const stage = $('ds-charts'); stage.classList.remove('ds-slide-transition'); stage.replaceChildren(); stage.classList.toggle('ds-positioned',slide.charts.length > 0 && slide.charts.every(chart=>chart.position)); stage.classList.toggle('ds-structural-stage', !slide.charts.length);
    if (!slide.charts.length) structuralDashboard(stage, slide);
    for (const chart of slide.charts) {
      const card = node('article',undefined,'ds-chart'); card.setAttribute('aria-label',chart.title); card.tabIndex = 0;
      let renderedPayload = null;
      if (chart.position) { const [left,top,width,height] = chart.position; Object.assign(card.style,{left:`${left}%`,top:`${top}%`,width:`${width}%`,height:`${height}%`}); }
      const message = node('div',`Rendering ${chart.title || 'chart'}…`,'ds-chart-message'); card.append(message);
      const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', chart.title); canvas.hidden = true; card.append(canvas);
      const zoom = chartZoomControls(canvas); card.append(zoom);
      if (chart.available) {
        const token = prepared.token;
        loadChartPayload(chart).then(payload => {
          if (!card.isConnected || prepared?.token !== token) return;
          renderedPayload = payload;
          canvas.hidden = false;
          requestAnimationFrame(() => {
            try { globalThis.renderDashboardChart(canvas, payload); zoom.hidden = false; message.remove(); }
            catch (error) { canvas.hidden = true; message.textContent = error.message || `Unable to render ${chart.title || 'chart'}.`; }
          });
        }).catch(error => {
          if (prepared?.token === token) message.textContent = error.message || `Unable to render ${chart.title || 'chart'}.`;
        });
      } else message.textContent = `Unavailable source type: select a ${chart.source ? chart.source.toUpperCase() : 'supported'} CDR dataset.`;
      const data = node('button','', 'ds-chart-data'); data.type = 'button'; data.title = 'View dataset'; data.setAttribute('aria-label', 'View dataset'); data.disabled = !chart.available; data.onclick = safe(async () => { await openChartDataset(chart); });
      const expand = node('button', '', 'ds-chart-expand'); expand.type = 'button'; expand.title = 'Expand chart'; expand.setAttribute('aria-label', 'Expand chart'); expand.disabled = !chart.available; expand.onclick = safe(async event => { event.stopPropagation(); await openExpandedChart(chart, renderedPayload); });
      card.ondblclick = safe(async event => {
        if (!chart.available || event.target.closest('button, a, input, select, label')) return;
        await openExpandedChart(chart, renderedPayload);
      });
      const controls = node('div', undefined, 'ds-chart-controls'); controls.append(data, expand, zoom); card.append(controls);
      let hideTimer;
      const showControls = () => { clearTimeout(hideTimer); hideTimer = null; card.classList.add('ds-hover'); };
      const hideControls = () => { if (!hideTimer) hideTimer = setTimeout(() => { card.classList.remove('ds-hover'); hideTimer = null; }, 500); };
      card.onpointerenter = showControls;
      card.onpointerleave = hideControls;
      card.onfocusin = showControls;
      card.onfocusout = () => { if (!card.contains(document.activeElement)) hideControls(); };
      stage.append(card);
    }
    if (presentation.running) { stage.dataset.presentationEffect = presentation.effect; void stage.offsetWidth; stage.classList.add('ds-slide-transition'); }
    renderComments();
  }
  bind('ds-first',()=>{ stopPresentation(); slideIndex = 0; renderSlide(); });
  bind('ds-prev',()=>{ stopPresentation(); slideIndex--; renderSlide(); });
  bind('ds-next',()=>{ stopPresentation(); slideIndex++; renderSlide(); });
  bind('ds-last',()=>{ stopPresentation(); slideIndex = Math.max(0, (prepared?.slides.length || 1) - 1); renderSlide(); });
  $('ds-slide').onchange = () => { stopPresentation(); slideIndex = Number($('ds-slide').value); renderSlide(); };
  bind('ds-comment-add', async () => { const input = $('ds-comment-input'), comment = input.value.trim(); if (!comment || !definition) return; const key = currentSlideCommentKey(); definition.slide_comments ||= {}; const comments = definition.slide_comments[key] ||= []; if (comments.length >= 50) throw new Error('A slide can have at most 50 comments.'); comments.push(comment); input.value = ''; await persistComments(); renderComments(); });
  $('ds-comment-input').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); $('ds-comment-add').click(); } });
  bind('ds-presentation', () => { if (presentation.running) stopPresentation(); else overlay('ds-presentation-overlay', true); });
  bind('ds-presentation-close', () => overlay('ds-presentation-overlay', false));
  bind('ds-presentation-start', startPresentation);
  bind('ds-presentation-stop', stopPresentation);
  bind('ds-floating-filters', openFloatingFilters);
  bind('ds-filter-close', closeFilters);
  bind('ds-filter-close-action', closeFilters);
  const closeOnOutsidePointer = (id, close) => {
    const host = $(id);
    host.addEventListener('pointerdown', event => {
      const dialog = host.querySelector('[role=dialog]');
      if (dialog?.contains(event.target)) return;
      event.preventDefault();
      void close();
    });
  };
  closeOnOutsidePointer('ds-filter-overlay', closeFilters);
  closeOnOutsidePointer('ds-editor-overlay', closeTemplateEditor);
  closeOnOutsidePointer('ds-data-overlay', () => overlay('ds-data-overlay', false));
  closeOnOutsidePointer('ds-presentation-overlay', () => overlay('ds-presentation-overlay', false));
  bind('ds-viewer-close', async () => { stopPresentation(); if (!$('ds-chart-expanded-overlay').hidden) expandedChartOverlay(false); if (!$('ds-filter-overlay').hidden && !await closeFilters()) return; overlay('ds-viewer', false); });
  function loadDataPage(token, index, page) {
    const key = `${token}:${index}:${page}`;
    let request = dataPages.get(key);
    if (!request) {
      request = api(`/data/${token}/${index}?page=${page}`);
      dataPages.set(key, request);
      request.catch(() => dataPages.delete(key));
      while (dataPages.size > 24) dataPages.delete(dataPages.keys().next().value);
    }
    return request;
  }
  const prefetchDataPage = (token, index, page, totalPages) => {
    if (page >= 0 && page < totalPages) void loadDataPage(token, index, page).catch(() => undefined);
  };
  async function renderData() {
    const token = dataToken, index = dataIndex, requestedPage = dataPage, request = ++dataRequest;
    const host = $('ds-data-table');
    if (!host.querySelector('table')) host.textContent = 'Loading chart dataset…';
    const payload = await loadDataPage(token, index, requestedPage);
    if (request !== dataRequest || token !== dataToken || index !== dataIndex) return;
    dataPage = payload.page;
    let table = host.querySelector('table');
    const columns = JSON.stringify(payload.columns);
    if (!table || table.dataset.columns !== columns) {
      table = node('table'); table.dataset.columns = columns;
      const head = node('thead'), header = node('tr'); payload.columns.forEach(column => header.append(node('th', column))); head.append(header); table.append(head, node('tbody'));
      host.replaceChildren(table);
    }
    const body = table.tBodies[0];
    body.replaceChildren(...payload.rows.map(row => { const tr = node('tr'); row.forEach(value => tr.append(node('td', value))); return tr; }));
    const totalPages = Math.max(1, Math.ceil(payload.total / 100));
    $('ds-data-page').textContent = `${payload.total.toLocaleString()} rows · Page ${dataPage + 1} / ${totalPages}`;
    $('ds-data-first').disabled = $('ds-data-prev').disabled = dataPage === 0;
    $('ds-data-next').disabled = $('ds-data-last').disabled = dataPage >= totalPages - 1;
    $('ds-data-download').href = `/api/e2e-dashboards/data/${token}/${index}?download=true`;
    prefetchDataPage(token, index, dataPage - 1, totalPages);
    prefetchDataPage(token, index, dataPage + 1, totalPages);
    prefetchDataPage(token, index, totalPages - 1, totalPages);
  }
  bind('ds-data-first', async () => { dataPage = 0; await renderData(); });
  bind('ds-data-prev', async () => { dataPage = Math.max(0, dataPage - 1); await renderData(); });
  bind('ds-data-next', async () => { dataPage += 1; await renderData(); });
  bind('ds-data-last', async () => { const label = $('ds-data-page').textContent; const pages = Number(label.match(/\/ (\d+)$/)?.[1]) || 1; dataPage = pages - 1; await renderData(); });
  bind('ds-data-close',()=>overlay('ds-data-overlay',false));
  bind('ds-chart-expanded-close',()=>expandedChartOverlay(false));
  if ($('ds-edit')) bind('ds-edit',()=>{ const slide = prepared?.slides[slideIndex]; if (slide) openTemplateEditor(slide.focus_row); });
  bind('ds-editor-close', closeTemplateEditor);
  document.addEventListener('keydown',event=>{
    const visible = ['ds-chart-expanded-overlay','ds-editor-overlay','ds-data-overlay','ds-filter-overlay','ds-presentation-overlay','ds-viewer'].find(id=>!$(id).hidden && $(id).contains(document.activeElement)); if (!visible) return;
    const editing = event.target.closest?.('input,textarea,select,[contenteditable="true"]');
    if (visible === 'ds-viewer' && !editing && event.key === 'ArrowLeft' && slideIndex > 0) { event.preventDefault(); stopPresentation(); slideIndex -= 1; renderSlide(); return; }
    if (visible === 'ds-viewer' && !editing && event.key === 'ArrowRight' && slideIndex < (prepared?.slides.length || 1) - 1) { event.preventDefault(); stopPresentation(); slideIndex += 1; renderSlide(); return; }
    if (event.key === 'Escape') { event.preventDefault(); $({'ds-chart-expanded-overlay':'ds-chart-expanded-close','ds-editor-overlay':'ds-editor-close','ds-data-overlay':'ds-data-close','ds-filter-overlay':'ds-filter-close','ds-presentation-overlay':'ds-presentation-close','ds-viewer':'ds-viewer-close'}[visible]).click(); }
    if (event.key === 'Tab') { const controls = [...$(visible).querySelectorAll('button:not(:disabled),a[href],input,select,summary,[tabindex="0"]')].filter(el=>el.getClientRects().length); if (!controls.length) return; const first = controls[0], last = controls.at(-1); if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
  });
  window.addEventListener('message', event => {
    if (event.origin !== window.location.origin || event.source !== $('ds-editor-frame').contentWindow) return;
    if (event.data?.type === 'dashboard-analytic:template-saved') templateEditorSaved = true;
    if (event.data?.type === 'dashboard-analytic:close-template-editor') void closeTemplateEditor();
  });
  let navigationPromptOpen = false;
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a.module-tab, a.topnav-link-logout');
    if (!link || !dirty || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = new URL(link.href, window.location.href);
    if (target.href === window.location.href || target.origin !== window.location.origin || navigationPromptOpen) return;
    event.preventDefault();
    navigationPromptOpen = true;
    void (async () => {
      try {
        if (hasUnsavedFilterChanges()) {
          const choice = await window.showConfirmDialog(
            'This Dashboard has filter changes that have not been saved. Save them before leaving?',
            {
              title: 'Unsaved Dashboard filters',
              confirmLabel: 'Save Filters',
              secondaryLabel: 'Discard',
              cancelLabel: 'Cancel',
            },
          );
          if (choice === 'confirm') await save();
          else if (choice !== 'secondary') return;
        } else if (!await window.showConfirmDialog(
          'This Dashboard has unsaved changes. Discard them before leaving?',
          {title: 'Unsaved Dashboard changes', confirmLabel: 'Discard', cancelLabel: 'Cancel'},
        )) return;
        dirty = false;
        window.location.assign(target.href);
      } catch (error) {
        window.showInfoDialog(error instanceof Error ? error.message : 'Dashboard changes could not be saved.', {
          title: 'Save Dashboard filters failed', tone: 'error',
        });
      } finally {
        navigationPromptOpen = false;
      }
    })();
  }, true);
  window.addEventListener('beforeunload',event=>{ if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('auto-calculated-field-job-status',event=>{ const job = event.detail; if (definition && job?.id && ['ready','completed'].includes(job.status) && !completedFieldJobs.has(job.id)) { completedFieldJobs.add(job.id); changed(); } });
  safe(async ()=>{
    let last = '';
    try {
      last = sessionStorage.getItem(openStorageKey) || '';
      const cached = JSON.parse(sessionStorage.getItem(libraryStorageKey) || '{}');
      dashboards = cached && typeof cached === 'object' && !Array.isArray(cached)
        && Object.values(cached).every(item => item && typeof item === 'object' && typeof item.name === 'string') ? cached : {};
      if (Object.keys(dashboards).length) library();
    } catch (_) { dashboards = {}; }
    dashboards = await api(); library(); await refreshDashboardStatuses();
    if (dashboards[last]) await openDashboard(last);
  })();
  window.setInterval(refreshDashboardStatuses, 2000);
  window.addEventListener('dashboard-analytic:refresh-background-tasks', refreshDashboardStatuses);
  window.addEventListener('focus', refreshDashboardStatuses);
})();
