/* One filter DOM and one definition are shared between the page and the overlay. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('ds-config').textContent);
  const eventTimeFilteringDisabled = Boolean(config.ignore_event_time_filtering);
  const eventTimeFilteringDisabledReason = 'Date filters are disabled because Ignore event time filtering is enabled in Config.';
  const filterAliases = config.filter_aliases || {};
  let dashboards = {}, activeId = '', definition = null, savedDefinition = '', appliedFilterState = '', appliedSelectionState = '', appliedDashboardDefinition = null, prepared = null, slideIndex = 0;
  let sequence = 0, cacheLookupSequence = 0, timer, controller, preparing = null, preparingFilterState = '', preparationProgressTimer = 0, dirty = false, filterActionBusy = false, dataToken = '', dataEndpoint = '';
  let presentationTimer = 0;
  const presentation = {active: false, running: false, delay: 5000, transitionDuration: 1, effect: 'flip', showComments: true};
  let presentationCommentsWasOpen = false;
  const randomPresentationEffects = ['fade', 'slide', 'slide-left', 'zoom', 'rise', 'blur', 'rotate', 'flip', 'bounce', 'wipe', 'mosaic', 'curtain', 'blinds'];
  let lastRandomPresentationEffect = '';
  let facetOptions = {}, availableFields = [], facetFields = config.filter_fields || [], facetsLoading = false, facetsRefreshTimer = 0;
  const facetOptionRequests = new Map();
  let facetOptionRequestSequence = 0;
  const completedFieldJobs = new Set();
  const chartPayloads = new Map();
  const renderedChartPayloads = new Map();
  const preparedPayloads = new Map();
  const dashboardStatuses = new Map();
  // Do not let status polling replace an active explicitly requested
  // preparation with the previously-ready persisted Dashboard.
  const dashboardPreparationTokens = new Map();
  let dashboardStatusRefreshing = false;
  let expandedChartRequest = 0;
  let slidePreloadRequest = 0, expandedChartPreloadRequest = 0;
  let backgroundPreparationToken = '';
  let dateBounds = null, templateEditorSaved = false, templateEditorPreloadTimer = 0, dashboardPptColumnFilters = null;
  let dashboardPptJobs = [], dashboardPptCharts = [], dashboardPptChartsJobId = '', dashboardPptChartsRequest = 0;
  let dashboardPptJobsLoaded = false, dashboardPptJobsRefreshing = false;
  const openStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:open`;
  const libraryStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:library`;
  const scrollStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:scroll`;
  const preparedStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:prepared`;
  const universeStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:universes`;
  const presentationEffectStorageKey = 'dashboard-analytic:e2e-dashboards:presentation-effect';
  try {
    const storedPresentationEffect = localStorage.getItem(presentationEffectStorageKey);
    const effectSelect = $('ds-presentation-effect');
    if (storedPresentationEffect && [...effectSelect.options].some(option => option.value === storedPresentationEffect)) effectSelect.value = storedPresentationEffect;
  } catch (_) { /* Local storage is optional. */ }
  const navigationEntry = performance.getEntriesByType?.('navigation')?.[0];
  const restorePageState = navigationEntry?.type === 'reload';
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
  const rememberScroll = () => { try { sessionStorage.setItem(scrollStorageKey, String(window.scrollY)); } catch (_) { /* Storage is optional. */ } };
  const restoreScroll = () => {
    try {
      const top = Number(sessionStorage.getItem(scrollStorageKey));
      if (!Number.isFinite(top) || top <= 0) return;
      let attempts = 0;
      const restore = () => {
        window.scrollTo({top, left: 0, behavior: 'auto'});
        const maximumTop = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        if (attempts++ >= 24 || (maximumTop >= top && Math.abs(window.scrollY - top) < 2)) return;
        window.setTimeout(() => requestAnimationFrame(restore), 50);
      };
      requestAnimationFrame(() => requestAnimationFrame(restore));
    } catch (_) { /* Storage is optional. */ }
  };
  const resetScroll = () => {
    try { sessionStorage.removeItem(scrollStorageKey); } catch (_) { /* Storage is optional. */ }
    window.scrollTo({top: 0, left: 0, behavior: 'auto'});
  };
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  if (!restorePageState) resetScroll();
  window.addEventListener('pagehide', rememberScroll);
  window.addEventListener('beforeunload', rememberScroll);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') rememberScroll(); });
  const nextName = value => { let name = value, number = 2; while (Object.values(dashboards).some(item => item.name.toLowerCase() === name.toLowerCase())) name = `${value.slice(0, 108)} (${number++})`; return name; };
  const focusReturn = new Map();
  const status = message => { $('ds-status').textContent = message; };
  const backgroundWorkspaceName = () => document.querySelector('[data-header-active-workspace-name]')?.textContent?.trim() || 'Active workspace';
  const emitPreparationStatus = (statusValue, detail = '', token = backgroundPreparationToken, progress = null) => {
    if (!token || token !== backgroundPreparationToken) return;
    const rendering = detail.includes('Rendering Dashboard charts') || detail.includes('render Dashboard charts');
    const queued = String(statusValue || '').toLowerCase() === 'queued';
    window.dispatchEvent(new CustomEvent('dashboard-analytic:background-task', {detail: {
      id: token, workspace_id: config.workspace, workspace_name: backgroundWorkspaceName(), is_active: true,
      dashboard_name: definition?.name || 'Dashboard',
      label: queued
        ? (rendering ? 'Waiting to render Dashboard Charts' : 'Waiting to prepare Dashboard dataset')
        : (rendering ? 'Rendering Dashboard Charts' : 'Preparing Dashboard dataset'),
      detail, progress, status: statusValue,
      stop_task_id: `dashboard-prepare:${token}`,
      stop_url: `/api/background-tasks/${encodeURIComponent(config.workspace)}/stop`,
    }}));
    window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));
  };
  const dismissPreparationStatus = () => {
    if (!backgroundPreparationToken) return;
    clearTimeout(preparationProgressTimer); preparationProgressTimer = 0;
    emitPreparationStatus('complete');
    backgroundPreparationToken = '';
  };
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
  const zoomResetIcon = () => {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
    const circle = document.createElementNS(namespace, 'circle'); circle.setAttribute('cx', '10'); circle.setAttribute('cy', '10'); circle.setAttribute('r', '8');
    const handle = document.createElementNS(namespace, 'path'); handle.setAttribute('d', 'm16 16 6 6');
    const label = document.createElementNS(namespace, 'text'); label.setAttribute('x', '10'); label.setAttribute('y', '10.5'); label.setAttribute('text-anchor', 'middle'); label.setAttribute('dominant-baseline', 'middle'); label.setAttribute('font-family', 'Arial, sans-serif'); label.setAttribute('font-size', '8'); label.setAttribute('font-weight', '700'); label.textContent = '1:1';
    svg.append(circle, handle, label); return svg;
  };
  const option = (value, label) => { const el = node('option', label); el.value = value; return el; };
  const identity = value => String(value).toLocaleLowerCase().replace(/[^a-z0-9]/g, '');
  const datasetRecency = row => {
    const uploadedAt = Date.parse(row.uploaded_at || row.updated_at || row.processed_at || row.created_at || '');
    return Number.isFinite(uploadedAt) ? uploadedAt : Number(row.id) || 0;
  };
  const latestDatasetsForScope = scope => Object.fromEntries(['data', 'voice', 'speech'].map(kind => [kind,
    [...(config.datasets[kind] || [])]
      .sort((left, right) => datasetRecency(right) - datasetRecency(left) || Number(right.id) - Number(left.id))
      .slice(0, scope === 'multivendor' ? 1 : 2)
      .map(row => Number(row.id)),
  ]));
  const canonicalDashboardDefinition = value => {
    const definitionValue = structuredClone(value || {});
    definitionValue.datasets ||= {};
    for (const kind of ['data', 'voice', 'speech']) definitionValue.datasets[kind] ||= [];
    definitionValue.filters ||= {};
    definitionValue.custom_fields ||= [];
    definitionValue.hidden_filters ||= [];
    definitionValue.slide_comments ||= {};
    if (!definitionValue.date_from) definitionValue.date_from = 'Oldest';
    if (!definitionValue.date_to) definitionValue.date_to = 'Newest';
    return definitionValue;
  };
  const rememberedUniverse = id => {
    if (!id) return null;
    try {
      const stored = JSON.parse(sessionStorage.getItem(universeStorageKey) || '{}');
      const saved = stored?.[id];
      if (!saved || !['single', 'multivendor'].includes(saved.scope) || !saved.datasets) return null;
      const datasets = Object.fromEntries(['data', 'voice', 'speech'].map(kind => {
        const available = new Set((config.datasets?.[kind] || []).map(row => Number(row.id)));
        return [kind, (saved.datasets[kind] || []).map(Number).filter(datasetId => available.has(datasetId))];
      }));
      return {
        scope: saved.scope,
        datasets,
        date_from: /^\d{4}-\d{2}-\d{2}$/.test(String(saved.date_from || '')) || saved.date_from === 'Oldest' ? saved.date_from : 'Oldest',
        date_to: /^\d{4}-\d{2}-\d{2}$/.test(String(saved.date_to || '')) || saved.date_to === 'Newest' ? saved.date_to : 'Newest',
      };
    } catch (_) { return null; }
  };
  const hasStoredUniverse = value => Boolean(
    value && Object.prototype.hasOwnProperty.call(value, 'scope')
    && Object.prototype.hasOwnProperty.call(value, 'datasets')
    && Object.prototype.hasOwnProperty.call(value, 'date_from')
    && Object.prototype.hasOwnProperty.call(value, 'date_to')
  );
  const savedRuntimeDashboardDefinition = value => {
    const canonical = canonicalDashboardDefinition(value);
    if (hasStoredUniverse(value)) return canonical;
    return {
      ...canonical, scope: 'single', datasets: latestDatasetsForScope('single'), date_from: 'Oldest', date_to: 'Newest',
    };
  };
  const runtimeDashboardDefinition = (value, id = '') => ({
    ...savedRuntimeDashboardDefinition(value),
    ...(rememberedUniverse(id) || {}),
  });
  const rememberUniverse = () => {
    if (!activeId || !definition) return;
    try {
      const stored = JSON.parse(sessionStorage.getItem(universeStorageKey) || '{}');
      stored[activeId] = {
        scope: definition.scope || 'single', datasets: structuredClone(definition.datasets || {}),
        date_from: definition.date_from || 'Oldest', date_to: definition.date_to || 'Newest',
      };
      sessionStorage.setItem(universeStorageKey, JSON.stringify(stored));
    } catch (_) { /* Session storage is optional. */ }
  };
  const persistedDashboardDefinition = value => canonicalDashboardDefinition(value);
  const canonicalize = value => {
    if (Array.isArray(value)) return value.map(canonicalize);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
  };
  const canonicalSetValues = values => [...new Set(values || [])].sort((left, right) => {
    const leftKey = JSON.stringify(left), rightKey = JSON.stringify(right);
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
  const canonicalSelectionDefinition = value => {
    const selection = canonicalDashboardDefinition(value);
    selection.datasets = Object.fromEntries(Object.entries(selection.datasets).map(([kind, ids]) => [kind, canonicalSetValues(ids)]));
    selection.filters = Object.fromEntries(Object.entries(selection.filters).map(([field, values]) => [field, canonicalSetValues(values)]));
    selection.custom_fields = canonicalSetValues(selection.custom_fields);
    selection.hidden_filters = canonicalSetValues(selection.hidden_filters);
    if (dateBounds) {
      if (selection.date_from !== 'Oldest' && (selection.date_from < dateBounds.min || selection.date_from > dateBounds.max)) selection.date_from = dateBounds.min;
      if (selection.date_to !== 'Newest' && (selection.date_to < dateBounds.min || selection.date_to > dateBounds.max)) selection.date_to = dateBounds.max;
    }
    return selection;
  };
  const definitionFingerprint = value => JSON.stringify(canonicalize(persistedDashboardDefinition(value)));
  const preparedStateFingerprint = value => {
    const preparedDefinition = canonicalSelectionDefinition(value);
    delete preparedDefinition.name;
    delete preparedDefinition.slide_comments;
    return JSON.stringify(canonicalize(preparedDefinition));
  };
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
  const appliedDefinition = () => appliedDashboardDefinition || savedDashboardDefinition();
  const filterControlState = (current, applied, saved, equal = sameFilterValues) => {
    if (!equal(current, applied)) return 'unapplied';
    return equal(applied, saved) ? '' : 'applied-unsaved';
  };
  const filterState = field => filterControlState(definition?.filters?.[field], appliedDefinition().filters?.[field], savedDashboardDefinition().filters?.[field]);
  const sourceState = kind => filterControlState(
    definition?.datasets?.[kind], appliedDefinition().datasets?.[kind], savedDashboardDefinition().datasets?.[kind],
  );
  const scopeState = () => filterControlState(
    definition?.scope || 'single', appliedDefinition().scope || 'single', savedDashboardDefinition().scope || 'single',
    (left, right) => left === right,
  );
  const dateState = key => filterControlState(
    definition?.[key], appliedDefinition()[key], savedDashboardDefinition()[key], (left, right) => left === right,
  );
  const updateFilterControlState = (element, state, date = false) => {
    element.classList.toggle(date ? 'ds-date-picker-unsaved' : 'ds-filter-unsaved', state === 'unapplied');
    element.classList.toggle(date ? 'ds-date-picker-applied-unsaved' : 'ds-filter-applied-unsaved', state === 'applied-unsaved');
  };
  const filterStateFingerprint = value => {
    const selection = canonicalSelectionDefinition(value);
    return JSON.stringify(canonicalize({
      filters: selection.filters, custom_fields: selection.custom_fields, hidden_filters: selection.hidden_filters,
    }));
  };
  const universeStateFingerprint = value => {
    const selection = canonicalSelectionDefinition(value);
    return JSON.stringify(canonicalize({
      datasets: selection.datasets, scope: selection.scope || 'single',
      date_from: selection.date_from || 'Oldest', date_to: selection.date_to || 'Newest',
    }));
  };
  const preparationStateFingerprint = value => {
    const selection = canonicalSelectionDefinition(value);
    return JSON.stringify(canonicalize({
      datasets: selection.datasets, scope: selection.scope || 'single', filters: selection.filters,
      custom_fields: selection.custom_fields, hidden_filters: selection.hidden_filters,
      date_from: selection.date_from || 'Oldest', date_to: selection.date_to || 'Newest',
    }));
  };
  const selectionStateFingerprint = value => {
    const selection = canonicalSelectionDefinition(value);
    return JSON.stringify(canonicalize({
      datasets: selection.datasets, filters: selection.filters, custom_fields: selection.custom_fields,
      hidden_filters: selection.hidden_filters, date_from: selection.date_from || 'Oldest', date_to: selection.date_to || 'Newest',
    }));
  };
  const hasUnsavedFilterChanges = () => Boolean(definition) && filterStateFingerprint(definition) !== filterStateFingerprint(savedDashboardDefinition());
  const hasUnappliedFilterChanges = () => Boolean(definition)
    && filterStateFingerprint(definition) !== filterStateFingerprint(appliedDefinition());
  const hasUnsavedUniverseChanges = () => Boolean(definition)
    && universeStateFingerprint(definition) !== universeStateFingerprint(savedDashboardDefinition());
  const hasUnappliedUniverseChanges = () => Boolean(definition)
    && universeStateFingerprint(definition) !== universeStateFingerprint(appliedDefinition());
  const hasAppliedUnsavedFilterChanges = () => Boolean(
    prepared?.token && appliedDashboardDefinition
    && filterStateFingerprint(appliedDashboardDefinition) !== filterStateFingerprint(savedDashboardDefinition())
  );
  const dashboardNeedsRefresh = () => Boolean(
    definition && prepared && preparationStateFingerprint(definition) !== appliedFilterState,
  );
  const universeNeedsRefresh = () => {
    if (!definition || !prepared) return false;
    return universeStateFingerprint(definition) !== universeStateFingerprint(appliedDashboardDefinition || definition);
  };
  const syncPreparationRefresh = () => {
    const refresh = $('ds-preparing-refresh');
    const ready = $('ds-preparing').dataset.state === 'ready';
    const stale = universeNeedsRefresh() && ready;
    refresh.hidden = !ready || !dashboardNeedsRefresh();
    refresh.disabled = !dashboardNeedsRefresh() || !ready || Boolean(preparing);
    $('ds-preparing-ready').hidden = stale;
    $('ds-preparing-out-of-sync').hidden = !stale;
  };
  const updateFilterActionState = () => {
    $('ds-save').disabled = !hasUnsavedFilterChanges() || filterActionBusy;
    $('ds-apply-filters').disabled = !hasUnappliedFilterChanges() || filterActionBusy;
    $('ds-save-universe').disabled = !hasUnsavedUniverseChanges() || filterActionBusy;
    $('ds-apply-universe').disabled = !hasUnappliedUniverseChanges() || filterActionBusy;
    $('ds-reload-universe').disabled = !hasUnsavedUniverseChanges() || filterActionBusy;
    syncPreparationRefresh();
  };
  const api = async (path = '', method = 'GET', body, signal) => {
    const response = await fetch(`/api/e2e-dashboards${path}`, {method, signal, cache: 'no-store', headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    const contentType = String(response.headers.get('content-type') || '').toLocaleLowerCase();
    const payload = contentType.includes('application/json') ? await response.json() : null;
    if (!response.ok) {
      if (!payload && (response.redirected || response.url.includes('/login'))) {
        throw new Error('Your session has expired. Please sign in again.');
      }
      if (!payload) {
        throw new Error(`The Dashboard API returned an unexpected ${response.status} response. Please reload the page and try again.`);
      }
      const error = new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail));
      error.status = response.status;
      throw error;
    }
    if (!payload) throw new Error('The Dashboard API returned HTML instead of JSON. Please reload the page and try again.');
    return payload;
  };
  const safe = fn => async (...args) => { try { await fn(...args); } catch (error) { if (error.name !== 'AbortError') { status(error.message); if (window.showInfoDialog) window.showInfoDialog(error.message, {title:'E2E Dashboards',tone:'error'}); } } };
  const bind = (id, fn) => $(id).addEventListener('click', safe(fn));
  const dashboardIsReady = id => Boolean(id && !dashboardPreparationTokens.has(id) && dashboardStatuses.get(id)?.state === 'ready');
  const dashboardIsPreparing = id => Boolean(id && (
    dashboardPreparationTokens.has(id)
    || ['loading-data', 'rendering', 'data-queued', 'charts-queued'].includes(dashboardStatuses.get(id)?.state)
  ));
  const setActiveDashboardHeading = name => {
    const heading = $('ds-active-dashboard-heading');
    heading.replaceChildren(document.createTextNode(name ? 'Active Dashboard: ' : 'Active Dashboard'));
    if (name) heading.append(node('span', name.toUpperCase(), 'ds-active-dashboard-name'));
  };
  const syncDashboardPptActions = () => {
    document.querySelectorAll('[data-dashboard-ppt-id]').forEach(button => {
      button.disabled = !dashboardIsReady(button.dataset.dashboardPptId);
    });
    const activePptReady = dashboardIsReady(activeId) && Boolean(prepared?.slides?.length);
    $('ds-generate-ppt').disabled = !activePptReady;
    $('ds-viewer-export-ppt').disabled = !activePptReady;
  };
  const syncDashboardViewActions = () => {
    document.querySelectorAll('[data-dashboard-view-id]').forEach(button => {
      const id = button.dataset.dashboardViewId;
      button.disabled = dashboardIsPreparing(id) || (id === activeId && $('ds-view').disabled);
    });
  };
  const setViewEnabled = enabled => { $('ds-view').disabled = !enabled; syncDashboardViewActions(); syncDashboardPptActions(); };
  const updateUnsavedFiltersBadge = () => {
    $('ds-unapplied-universe-badge').hidden = !hasUnappliedUniverseChanges();
    $('ds-unsaved-universe-badge').hidden = !hasUnsavedUniverseChanges();
    $('ds-unapplied-filters-badge').hidden = !hasUnappliedFilterChanges();
    $('ds-unsaved-filters-badge').hidden = !hasUnsavedFilterChanges();
  };
  const updateDirtyState = () => { dirty = hasUnsavedDashboardChanges(); updateFilterActionState(); updateUnsavedFiltersBadge(); return dirty; };
  const updateSavedDefinition = updates => {
    try {
      savedDefinition = definitionFingerprint({...JSON.parse(savedDefinition || '{}'), ...updates});
    } catch (_) {
      savedDefinition = definitionFingerprint(definition);
    }
    updateDirtyState();
  };
  const setPreparationState = (state, phase = 'data') => {
    const notice = $('ds-preparing'), viewerNotice = $('ds-viewer-preparing');
    notice.hidden = state === 'hidden';
    viewerNotice.hidden = state !== 'preparing' || $('ds-viewer').hidden;
    notice.dataset.state = state;
    if (state !== 'ready') { $('ds-preparing-rows').hidden = true; $('ds-preparing-rows').textContent = ''; }
    const ready = state === 'ready';
    const refresh = $('ds-preparing-refresh');
    refresh.hidden = !ready || !dashboardNeedsRefresh();
    syncPreparationRefresh();
    if (state === 'hidden') return;
    const floatingFilters = $('ds-filter-panel').parentElement?.id === 'ds-filter-float';
    $('ds-preparing-title').textContent = ready ? 'Dashboard dataset is ready' : phase === 'rendering' ? 'Rendering Dashboard Charts' : 'Preparing Dashboard dataset';
    $('ds-preparing-detail').textContent = floatingFilters
      ? (ready
        ? 'Dataset and filters are ready. The Dashboard dataset is ready to use.'
        : phase === 'rendering' ? 'Charts are rendering with the current Dashboard scope.' : 'Dataset and filters are still loading. The Dashboard will update when preparation is complete.')
      : (ready
        ? "Datasets and filters are ready. You can now open the dashboard using 'View Dashboard' button below."
        : phase === 'rendering' ? 'Charts are rendering with the current Dashboard scope. View Dashboard will become available when rendering is complete.' : 'Dataset and filters are still loading. View Dashboard will become available when preparation is complete.');
  };
  const setPreparationProgress = (progress, detail = 'Preparing…') => {
    const numeric = Number(progress);
    const known = progress !== null && progress !== undefined && progress !== '' && Number.isFinite(numeric);
    const percent = known ? Math.max(0, Math.min(100, Math.round(numeric))) : 0;
    for (const [rootId, barId, labelId] of [
      ['ds-preparing-progress', 'ds-preparing-progress-bar', 'ds-preparing-progress-label'],
      ['ds-viewer-preparing-progress', 'ds-viewer-preparing-progress-bar', 'ds-viewer-preparing-progress-label'],
    ]) {
      const root = $(rootId), bar = $(barId), label = $(labelId);
      root.classList.toggle('is-indeterminate', !known);
      if (known) {
        root.setAttribute('aria-valuemin', '0'); root.setAttribute('aria-valuemax', '100'); root.setAttribute('aria-valuenow', String(percent));
        bar.style.width = `${percent}%`;
      } else {
        root.removeAttribute('aria-valuenow'); bar.style.width = '';
      }
      label.textContent = known ? `${detail} · ${percent}%` : detail;
    }
    $('ds-preparing-detail').textContent = detail;
    $('ds-viewer-preparing-detail').textContent = detail;
  };
  const monitorPreparationProgress = token => {
    clearTimeout(preparationProgressTimer);
    setPreparationProgress(null, 'Waiting for the server to register the Dashboard preparation task');
    emitPreparationStatus('queued', 'Waiting for the server to register the Dashboard preparation task', token);
    const refresh = async () => {
      if (!token || token !== backgroundPreparationToken) return;
      try {
        const payload = await api(`/preparation-progress/${encodeURIComponent(token)}`);
        if (token === backgroundPreparationToken) {
          const queued = payload.status === 'queued';
          setPreparationProgress(queued ? null : payload.progress, payload.detail);
          emitPreparationStatus(payload.status || 'processing', payload.detail, token, queued ? null : payload.progress);
        }
      } catch (_) {
        // The task may not yet be registered or may have just completed.
      } finally {
        if (token === backgroundPreparationToken) preparationProgressTimer = setTimeout(refresh, 400);
      }
    };
    void refresh();
  };
  function overlay(id, show) {
    const el = $(id);
    if (show) { focusReturn.set(id, document.activeElement); el.hidden = false; el.querySelector('[role=dialog]').focus(); }
    else { el.hidden = true; focusReturn.get(id)?.focus(); }
    if (id === 'ds-viewer') $('ds-viewer-preparing').hidden = !show || $('ds-preparing').dataset.state !== 'preparing';
    if (id === 'ds-viewer' && show) scheduleTemplateEditorPreload();
    document.body.style.overflow = [...document.querySelectorAll('.ds-overlay')].some(el => !el.hidden) ? 'hidden' : '';
  }
  const restoreAppliedFilterSelection = () => {
    const applied = canonicalDashboardDefinition(appliedDefinition());
    definition.filters = structuredClone(applied.filters);
    definition.custom_fields = structuredClone(applied.custom_fields);
    definition.hidden_filters = structuredClone(applied.hidden_filters);
    sources();
    facets();
    updateDirtyState();
  };
  const resolveUnappliedFilterChanges = async () => {
    if (!hasUnappliedFilterChanges()) return 'unchanged';
    const choice = await window.showConfirmDialog(
      'This Dashboard has filter changes that have not been applied. Apply, save or discard them before continuing?',
      {
        title: 'Unapplied Dashboard filters',
        confirmLabel: 'Apply Filters and Continue',
        secondaryLabel: 'Discard and Continue',
        tertiaryLabel: 'Save and Continue',
        cancelLabel: 'Cancel',
        wideActions: true,
      },
    );
    if (!choice) return null;
    if (!$('ds-filter-overlay').hidden) await closeFilters();
    if (choice === 'confirm') {
      await prepare();
      return 'applied';
    }
    if (choice === 'tertiary') {
      if (hasUnsavedFilterChanges()) await save();
      else await prepare();
      return 'saved';
    }
    restoreAppliedFilterSelection();
    status('Discarded unapplied filter changes.');
    return 'discarded';
  };
  const openActiveDashboardViewer = async () => {
    const filterDecision = await resolveUnappliedFilterChanges();
    if (!filterDecision) return;
    if (!$('ds-filter-overlay').hidden) await closeFilters();
    const needsPreparation = !prepared || preparationStateFingerprint(definition) !== appliedFilterState;
    if (needsPreparation) {
      resetViewerForDashboard();
      const needsDataPreparation = selectionStateFingerprint(definition) !== appliedSelectionState;
      setPreparationState('preparing', needsDataPreparation ? 'data' : 'rendering');
    }
    overlay('ds-viewer', true);
    if (needsPreparation) await prepare();
    if (prepared?.slides.length) renderSlide();
  };
  async function queueDashboardPptExport(id, item, {chooseScope = false} = {}) {
    let exportDefinition = item;
    let preparationToken = null;
    let filterDecision = 'unchanged';
    if (chooseScope) {
      const scopeChoice = await window.showConfirmDialog(
        `Choose the comparison scope for the PowerPoint presentation of “${item.name}”.`,
        {
          title: 'Choose PowerPoint Scope',
          confirmLabel: 'Operator Comparison',
          secondaryLabel: 'Multivendor Comparison',
          cancelLabel: 'Cancel',
          wideActions: true,
        },
      );
      if (!scopeChoice) return;
      exportDefinition = JSON.parse(JSON.stringify(item));
      exportDefinition.scope = scopeChoice === 'secondary' ? 'multivendor' : 'single';
      // Library exports always build their temporary universe from the latest
      // CDRs appropriate to the Scope selected in this dialog.
      delete exportDefinition.datasets;
      delete exportDefinition.date_from;
      delete exportDefinition.date_to;
      let scopePreview;
      try {
        scopePreview = await api(`/prefetched/${encodeURIComponent(id)}?use_scope_universe=1`, 'POST', exportDefinition);
      } catch (error) {
        if (error.status !== 409) throw error;
        scopePreview = await api(`/prepare?dashboard_id=${encodeURIComponent(id)}&use_scope_universe=1`, 'POST', exportDefinition);
      }
      const chartIndexes = (scopePreview.slides || []).flatMap(slide => (slide.charts || []))
        .filter(chart => chart.available).map(chart => chart.index);
      // A selected Scope may use a universe that has not been warmed yet.
      // Generate every required model before handing the snapshot to the PPT
      // worker, so the newly queued job always has a complete chart set.
      for (const index of chartIndexes) {
        await api(`/chart/${encodeURIComponent(scopePreview.token)}/${index}`);
      }
      preparationToken = scopePreview.token;
    } else {
      filterDecision = id === activeId ? await resolveUnappliedFilterChanges() : 'unchanged';
      if (!filterDecision) return;
      if (id === activeId && (!prepared || preparationStateFingerprint(definition) !== appliedFilterState)) await prepare();
      if (id === activeId && prepared?.token) {
        const exportAppliedDefinition = appliedDashboardDefinition || definition;
        if (filterDecision !== 'unchanged') {
          exportDefinition = JSON.parse(JSON.stringify(exportAppliedDefinition));
          preparationToken = prepared.token;
        } else if (hasAppliedUnsavedFilterChanges()) {
          const choice = await window.showConfirmDialog(
            'This Dashboard has applied filters that have not been saved. Which filters should the PowerPoint use?',
            {
              title: 'Choose PowerPoint filters',
              confirmLabel: 'Use Current Filters',
              secondaryLabel: 'Use Saved Filters',
              cancelLabel: 'Cancel',
              wideActions: true,
            },
          );
          if (choice === 'confirm') {
            exportDefinition = JSON.parse(JSON.stringify(exportAppliedDefinition));
            preparationToken = prepared.token;
          } else if (choice === 'secondary') exportDefinition = savedDashboardDefinition();
          else return;
        } else {
          exportDefinition = JSON.parse(JSON.stringify(exportAppliedDefinition));
          preparationToken = prepared.token;
        }
      }
    }
    if (!chooseScope && filterDecision === 'unchanged' && !hasAppliedUnsavedFilterChanges()) {
      const accepted = await window.showConfirmDialog(
        `Generate a PowerPoint presentation for “${exportDefinition.name}”?`,
        {title: 'Generate PPT Dashboard', confirmLabel: 'Generate PPT'},
      );
      if (!accepted) return;
    }
    await api(`/${encodeURIComponent(id)}/export-ppt`, 'POST', {
      definition: exportDefinition,
      preparation_token: preparationToken,
    });
    status(`Dashboard PPT export queued for “${exportDefinition.name}”.`);
    await refreshDashboardPptJobs();
    window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));
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
      const nameCell = node('td'); nameCell.dataset.label = 'Dashboard';
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
          definition.name = result.name; $('ds-name').value = result.name;
          setActiveDashboardHeading(result.name);
          updateSavedDefinition({name: result.name});
          if (!$('ds-viewer').hidden) renderSlide();
        }
        library(); status(`Renamed Dashboard to “${result.name}”.`);
      });
      nameEditor.append(nameInput, nameSave); nameCell.append(nameEditor);
      const technologyCell = node('td', (item.technology || item.template_technology || 'nsa').toUpperCase()); technologyCell.dataset.label = 'NR Mode';
      const templateCell = node('td', item.template); templateCell.dataset.label = 'Template';
      row.append(nameCell, technologyCell, templateCell);
      const statusCell = node('td'); statusCell.dataset.label = 'Status';
      const dashboardStatus = dashboardStatuses.get(id) || {state: 'checking', label: 'Checking'};
      const statusBadge = node('span', dashboardStatus.label, `ds-dashboard-status ds-dashboard-status-${dashboardStatus.state}`);
      statusBadge.dataset.dashboardStatusId = id;
      statusBadge.title = dashboardStatus.detail || dashboardStatus.label;
      statusCell.append(statusBadge); row.append(statusCell);
      const actions = node('div', undefined, 'ds-dashboard-actions');
      const action = (label, glyph, handler, tone = '') => {
        const button = node('button', glyph, `icon-action ds-dashboard-action ${tone}`); button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.onclick = safe(handler); actions.append(button); return button;
      };
      action(id === activeId ? 'Close Dashboard' : 'Open Dashboard', id === activeId ? '🚪' : '📂', async () => {
        if (id === activeId) { if (await confirmDiscard()) closeDashboard(); }
        else if (await confirmDiscard()) await openDashboard(id);
      }, id === activeId ? 'ds-dashboard-close' : 'ds-dashboard-open');
      const view = action('View Dashboard', '◉', async () => {
        if (id !== activeId) {
          if (!await confirmDiscard()) return;
          const loading = openDashboard(id);
          overlay('ds-viewer', true);
          await loading;
        } else {
          await openActiveDashboardViewer();
        }
      }, 'ds-dashboard-view');
      view.dataset.dashboardViewId = id;
      view.disabled = dashboardIsPreparing(id) || (id === activeId && $('ds-view').disabled);
      action('Duplicate Dashboard', '⧉', async () => { if (await confirmDiscard()) await duplicateDashboard(id); });
      action('Export Dashboard', '', () => exportDashboard(id, item), 'ds-dashboard-export');
      const ppt = action('Generate PPT Dashboard', '', () => queueDashboardPptExport(id, item, {chooseScope: true}), 'ds-dashboard-ppt');
      ppt.dataset.dashboardPptId = id;
      ppt.disabled = dashboardStatus.state !== 'ready';
      action('Delete Dashboard', '×', async () => { await deleteDashboard(id); }, 'danger-button');
      const cell = node('td'); cell.dataset.label = 'Actions'; cell.append(actions); row.append(cell); body.append(row);
    }
  }
  const renderDashboardStatuses = () => {
    document.querySelectorAll('[data-dashboard-status-id]').forEach(badge => {
      const value = dashboardStatuses.get(badge.dataset.dashboardStatusId) || {state: 'checking', label: 'Checking'};
      badge.className = `ds-dashboard-status ds-dashboard-status-${value.state}`;
      badge.textContent = value.label;
      badge.title = value.detail || value.label;
    });
    syncDashboardViewActions();
    syncDashboardPptActions();
  };
  const jobAction = (label, className, handler, glyph = '') => {
    const button = node('button', glyph, className); button.type = 'button';
    button.title = label; button.setAttribute('aria-label', label); button.onclick = safe(handler); return button;
  };
  const closeDashboardPptFilters = () => {
    $('ds-ppt-filter-dialog-content').replaceChildren();
    overlay('ds-ppt-filter-overlay', false);
  };
  const showDashboardPptFilters = (dashboardName, content) => {
    $('ds-ppt-filter-dialog-title').textContent = `Filters: ${dashboardName}`;
    $('ds-ppt-filter-dialog-content').replaceChildren(content.cloneNode(true));
    overlay('ds-ppt-filter-overlay', true);
  };
  const hideDashboardPptFilterTooltip = () => { $('ds-ppt-filter-tooltip').hidden = true; };
  const showDashboardPptFilterTooltip = (trigger, content) => {
    const tooltip = $('ds-ppt-filter-tooltip');
    tooltip.replaceChildren(content.cloneNode(true));
    tooltip.hidden = false;
    requestAnimationFrame(() => {
      const triggerBounds = trigger.getBoundingClientRect();
      const tooltipBounds = tooltip.getBoundingClientRect();
      const margin = 12;
      const below = triggerBounds.bottom + 8;
      const top = below + tooltipBounds.height <= window.innerHeight - margin
        ? below : Math.max(margin, triggerBounds.top - tooltipBounds.height - 8);
      tooltip.style.left = `${Math.max(margin, Math.min(triggerBounds.left, window.innerWidth - tooltipBounds.width - margin))}px`;
      tooltip.style.top = `${top}px`;
    });
  };
  bind('ds-ppt-filter-dialog-close', closeDashboardPptFilters);
  const dashboardPptFilterContent = job => {
    const content = node('div', undefined, 'ds-ppt-job-filter-content');
    const filterGroups = new Map();
    const otherFilters = [];
    const filterLines = Array.isArray(job?.filters) ? job.filters : [];
    filterLines.forEach((line) => {
      const value = String(line || '').trim();
      const match = /^(?:CDR\s+)?(Data|Voice|Speech)\s*:\s*(.*)$/i.exec(value);
      if (!match) { if (value) otherFilters.push(value); return; }
      const kind = `${match[1][0].toUpperCase()}${match[1].slice(1).toLowerCase()}`;
      const names = match[2].split(/\s*,\s*/).map(name => name.trim()).filter(Boolean);
      filterGroups.set(kind, [...(filterGroups.get(kind) || []), ...names]);
    });
    for (const kind of ['Data', 'Voice', 'Speech']) {
      const names = filterGroups.get(kind);
      if (!names?.length) continue;
      const group = node('span', undefined, 'ds-ppt-job-filter-group');
      group.append(node('strong', `${kind}:`, 'ds-ppt-job-filter-kind'));
      names.forEach(name => group.append(node('span', name, 'ds-ppt-job-filter-value')));
      content.append(group);
    }
    otherFilters.forEach((line) => {
      const detail = node('span', undefined, 'ds-ppt-job-filter-detail');
      const separator = line.indexOf(':');
      if (separator > 0) {
        detail.append(node('strong', line.slice(0, separator + 1), 'ds-ppt-job-filter-kind'), document.createTextNode(line.slice(separator + 1)));
      } else detail.textContent = line;
      content.append(detail);
    });
    if (!content.childElementCount) content.textContent = 'No filters applied';
    return content;
  };
  const showDashboardPptJobFilterTooltip = (trigger, job) => showDashboardPptFilterTooltip(trigger, dashboardPptFilterContent(job));
  const showDashboardPptJobFilters = job => {
    hideDashboardPptFilterTooltip();
    showDashboardPptFilters(String(job?.dashboard_name || 'Dashboard'), dashboardPptFilterContent(job));
  };
  const setDashboardPptChartBadges = job => {
    for (const [id, value] of [
      ['ds-ppt-charts-dashboard', job?.dashboard_name],
      ['ds-ppt-charts-date', job?.date ? String(job.date).replace('\n', ' · ') : ''],
      ['ds-ppt-charts-scope', job?.scope],
    ]) {
      const badge = $(id);
      badge.textContent = value || '';
      badge.hidden = !value;
    }
    const filtersBadge = $('ds-ppt-charts-filters');
    filtersBadge.hidden = !job;
    filtersBadge.dataset.jobId = job?.id || '';
    filtersBadge.setAttribute('aria-label', job ? `View filters used for ${job.dashboard_name}` : 'View filters');
  };
  const selectedDashboardPptChartJob = () => dashboardPptJobs.find(job => String(job.id) === $('ds-ppt-charts-filters').dataset.jobId);
  $('ds-ppt-charts-filters').addEventListener('pointerenter', () => {
    const job = selectedDashboardPptChartJob();
    if (job) showDashboardPptJobFilterTooltip($('ds-ppt-charts-filters'), job);
  });
  $('ds-ppt-charts-filters').addEventListener('pointerleave', hideDashboardPptFilterTooltip);
  $('ds-ppt-charts-filters').addEventListener('focus', () => {
    const job = selectedDashboardPptChartJob();
    if (job) showDashboardPptJobFilterTooltip($('ds-ppt-charts-filters'), job);
  });
  $('ds-ppt-charts-filters').addEventListener('blur', hideDashboardPptFilterTooltip);
  $('ds-ppt-charts-filters').addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    const job = selectedDashboardPptChartJob();
    if (job) showDashboardPptJobFilters(job);
  });
  const showDashboardPptChart = async index => {
    if (!dashboardPptCharts.length) return;
    const chartIndex = Math.max(0, Math.min(Number(index) || 0, dashboardPptCharts.length - 1));
    const chart = dashboardPptCharts[chartIndex];
    if (!chart.payload_url) throw new Error('This earlier PPT Job does not contain an interactive Canvas model. Relaunch it to add interactive chart previews.');
    const response = await fetch(chart.payload_url, {cache: 'no-store', credentials: 'same-origin'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Unable to load the Dashboard chart model.');
    await openExpandedChart(chart, payload, 'ppt');
  };
  const renderDashboardPptCharts = (payload, job) => {
    $('ds-ppt-charts-panel').hidden = false;
    dashboardPptCharts = Array.isArray(payload.charts) ? payload.charts : [];
    dashboardPptChartsJobId = String(job?.id || '');
    $('ds-ppt-charts-count').textContent = `${dashboardPptCharts.length} chart${dashboardPptCharts.length === 1 ? '' : 's'}`;
    $('ds-ppt-charts-empty').hidden = dashboardPptCharts.length > 0;
    $('ds-ppt-charts-copy').textContent = dashboardPptCharts.length
      ? `Cached charts generated for Dashboard "${job.dashboard_name}". Click any chart to enlarge it.`
      : 'This PowerPoint job does not contain any Dashboard charts.';
    setDashboardPptChartBadges(job);
    const thumbnailJobId = dashboardPptChartsJobId;
    const cachedImage = chart => {
      const image = node('img');
      image.src = chart.image_url;
      image.alt = chart.title || 'Dashboard chart';
      image.loading = 'lazy';
      return image;
    };
    const cards = dashboardPptCharts.map((chart, index) => {
      const card = node('article', undefined, 'report-chart-card');
      card.tabIndex = 0;
      const head = node('div', undefined, 'report-chart-card-head');
      const heading = node('div');
      heading.append(node('h3', chart.title || 'Dashboard chart'));
      heading.append(node('p', [chart.slide ? `Slide ${chart.slide}` : '', chart.source || '', chart.chart_type || ''].filter(Boolean).join(' · ')));
      head.append(heading);
      const preview = node('div', undefined, 'ds-ppt-chart-thumbnail');
      if (chart.payload_url && globalThis.renderDashboardChart) {
        const canvas = node('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', chart.title || 'Dashboard chart');
        preview.append(canvas);
        fetch(chart.payload_url, {cache: 'no-store', credentials: 'same-origin'})
          .then(async response => {
            const model = await response.json();
            if (!response.ok) throw new Error(model.detail || 'Unable to load chart model.');
            if (dashboardPptChartsJobId !== thumbnailJobId || !canvas.isConnected) return;
            globalThis.renderDashboardChart(canvas, model);
          })
          .catch(() => {
            if (dashboardPptChartsJobId === thumbnailJobId && preview.isConnected) preview.replaceChildren(cachedImage(chart));
          });
      } else preview.append(cachedImage(chart));
      card.append(head, preview);
      card.addEventListener('click', safe(() => showDashboardPptChart(index)));
      card.addEventListener('keydown', safe(async event => {
        if (!['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        await showDashboardPptChart(index);
      }));
      return card;
    });
    $('ds-ppt-charts-body').replaceChildren(...cards);
  };
  const loadDashboardPptCharts = async (jobId, scrollIntoView = false) => {
    const job = dashboardPptJobs.find(item => String(item.id) === String(jobId));
    if (!job?.charts_api_url) return;
    $('ds-ppt-charts-panel').hidden = false;
    const request = ++dashboardPptChartsRequest;
    dashboardPptChartsJobId = String(job.id);
    $('ds-ppt-chart-job').value = String(job.id);
    renderDashboardPptJobPickerLabel($('ds-ppt-chart-job-picker-label'), job);
    $('ds-ppt-charts-copy').textContent = `Loading cached charts for Dashboard "${job.dashboard_name}"…`;
    $('ds-ppt-charts-empty').hidden = true;
    try {
      const payload = await api(`/ppt-jobs/${job.id}/charts.json`);
      if (request !== dashboardPptChartsRequest) return;
      renderDashboardPptCharts(payload, job);
      if (scrollIntoView) {
        const panel = document.querySelector('.ds-ppt-charts-panel');
        panel.open = true;
        panel.scrollIntoView({behavior: 'smooth', block: 'start'});
      }
    } catch (error) {
      if (request !== dashboardPptChartsRequest) return;
      dashboardPptCharts = [];
      dashboardPptChartsJobId = '';
      $('ds-ppt-charts-body').replaceChildren();
      $('ds-ppt-charts-count').textContent = '0 charts';
      $('ds-ppt-charts-empty').hidden = false;
      $('ds-ppt-charts-copy').textContent = error instanceof Error ? error.message : 'Dashboard charts could not be loaded.';
    }
  };
  const dashboardPptChartFilterControls = [...document.querySelectorAll('[data-dashboard-ppt-chart-filter]')];
  const dashboardPptChartFilterState = {nr_mode: '', dashboard: '', template: '', scope: ''};
  const normalizeDashboardPptChartFilter = value => String(value || '').trim().toLocaleLowerCase();
  const dashboardPptChartMetadata = job => ({
    nr_mode: normalizeDashboardPptChartFilter(job.nr_mode),
    dashboard: normalizeDashboardPptChartFilter(job.dashboard_name),
    template: normalizeDashboardPptChartFilter(job.template),
    scope: normalizeDashboardPptChartFilter(job.scope),
  });
  const matchesDashboardPptChartFilters = job => {
    const metadata = dashboardPptChartMetadata(job);
    return Object.entries(dashboardPptChartFilterState).every(([field, selected]) => !selected || metadata[field] === selected);
  };
  const refreshDashboardPptChartFilterChoices = jobs => {
    const labelFor = (field, job) => ({
      nr_mode: String(job.nr_mode || '').toUpperCase(), dashboard: job.dashboard_name,
      template: job.template, scope: job.scope,
    }[field] || '');
    for (const control of dashboardPptChartFilterControls) {
      const field = control.dataset.dashboardPptChartFilter;
      const values = new Map();
      jobs.forEach(job => {
        const value = dashboardPptChartMetadata(job)[field];
        if (value && !values.has(value)) values.set(value, labelFor(field, job));
      });
      control.replaceChildren(option('', 'All'), ...[...values.entries()]
        .sort((left, right) => left[1].localeCompare(right[1]))
        .map(([value, label]) => option(value, label)));
      control.value = dashboardPptChartFilterState[field];
    }
  };
  const dashboardPptJobTimestampLabel = job => String(job?.date || '').replace('\n', ' · ');
  const renderDashboardPptJobPickerLabel = (container, job, emptyLabel = 'No generated Dashboard PPTs') => {
    container.replaceChildren();
    if (!job) { container.textContent = emptyLabel; return; }
    container.append(
      node('span', dashboardPptJobTimestampLabel(job), 'ds-ppt-chart-job-timestamp'),
      node('span', '•', 'ds-ppt-chart-job-separator'),
      node('strong', job.dashboard_name, 'ds-ppt-chart-job-dashboard'),
      node('span', '•', 'ds-ppt-chart-job-separator'),
      node('span', job.scope, 'ds-ppt-chart-job-scope'),
    );
  };
  const rebuildDashboardPptJobPicker = (available, emptyLabel) => {
    const selected = available.find(job => String(job.id) === $('ds-ppt-chart-job').value);
    renderDashboardPptJobPickerLabel($('ds-ppt-chart-job-picker-label'), selected, emptyLabel);
    $('ds-ppt-chart-job-picker-options').replaceChildren(...available.map(job => {
      const choice = node('button', undefined, 'chart-set-picker-option ds-ppt-chart-job-option');
      choice.type = 'button';
      choice.dataset.dashboardPptJobId = String(job.id);
      choice.setAttribute('role', 'option');
      choice.setAttribute('aria-selected', String(job === selected));
      renderDashboardPptJobPickerLabel(choice, job);
      return choice;
    }));
  };
  const syncDashboardPptChartJobs = (jobs, preferredJobId = '') => {
    dashboardPptJobs = jobs;
    const select = $('ds-ppt-chart-job');
    const previous = String(preferredJobId || select.value);
    const generated = jobs.filter(job => job.charts_api_url).sort((left, right) =>
      String(right.timestamp || '').localeCompare(String(left.timestamp || '')) || Number(right.id) - Number(left.id));
    refreshDashboardPptChartFilterChoices(generated);
    const available = generated.filter(matchesDashboardPptChartFilters);
    select.replaceChildren(...(available.length
      ? available.map(job => option(
        String(job.id),
        `${job.timestamp || String(job.date || '').replace(/[-:\s]/g, '').slice(0, 15)} • ${job.dashboard_name} • ${job.scope}`,
      ))
      : [option('', generated.length ? 'No matching Dashboard PPTs' : 'No generated Dashboard PPTs')]));
    select.disabled = available.length === 0;
    select.value = available.some(job => String(job.id) === previous) ? previous : String(available[0]?.id || '');
    const emptyLabel = generated.length ? 'No matching Dashboard PPTs' : 'No generated Dashboard PPTs';
    rebuildDashboardPptJobPicker(available, emptyLabel);
    if (!available.length) {
      ++dashboardPptChartsRequest;
      dashboardPptCharts = [];
      dashboardPptChartsJobId = '';
      $('ds-ppt-charts-body').replaceChildren();
      $('ds-ppt-charts-count').textContent = '0 charts';
      $('ds-ppt-charts-empty').hidden = false;
      $('ds-ppt-charts-copy').textContent = 'Select a completed Dashboard PowerPoint job to inspect its cached charts. Click any chart to enlarge it.';
      setDashboardPptChartBadges(null);
      $('ds-ppt-charts-panel').hidden = true;
      return;
    }
    if (dashboardPptChartsJobId !== select.value) void loadDashboardPptCharts(select.value);
  };
  $('ds-ppt-chart-job').addEventListener('change', safe(event => {
    rebuildDashboardPptJobPicker(
      dashboardPptJobs.filter(job => job.charts_api_url && matchesDashboardPptChartFilters(job)),
      'No matching Dashboard PPTs',
    );
    return loadDashboardPptCharts(event.target.value);
  }));
  $('ds-ppt-chart-job-picker-options').addEventListener('click', event => {
    const choice = event.target.closest('[data-dashboard-ppt-job-id]');
    if (!choice) return;
    $('ds-ppt-chart-job').value = choice.dataset.dashboardPptJobId || '';
    $('ds-ppt-chart-job-picker').open = false;
    $('ds-ppt-chart-job').dispatchEvent(new Event('change'));
  });
  document.addEventListener('pointerdown', event => {
    if ($('ds-ppt-chart-job-picker').open && !$('ds-ppt-chart-job-picker').contains(event.target)) $('ds-ppt-chart-job-picker').open = false;
  });
  dashboardPptChartFilterControls.forEach(control => control.addEventListener('change', () => {
    dashboardPptChartFilterState[control.dataset.dashboardPptChartFilter] = normalizeDashboardPptChartFilter(control.value);
    syncDashboardPptChartJobs(dashboardPptJobs);
  }));
  const renderDashboardPptJobs = (jobs, preferredJobId = '') => {
    const body = $('ds-ppt-jobs-body'); body.replaceChildren();
    $('ds-ppt-jobs-count').textContent = `Total Jobs: ${jobs.length}`;
    $('ds-ppt-jobs-empty').hidden = jobs.length > 0;
    for (const job of jobs) {
      const row = node('tr');
      for (const value of [job.id, job.generated_by, job.date, job.nr_mode || job.technology || job.type || '-', job.dashboard_name, job.scope]) row.append(node('td', String(value)));
      const filterLines = Array.isArray(job.filters) ? job.filters : [];
      const filterTooltip = filterLines.length ? filterLines.join('\n') : 'No filters applied';
      const filtersCell = node('td');
      const filtersIcon = node('button', '', 'ds-ppt-job-filters');
      filtersIcon.type = 'button';
      filtersIcon.setAttribute('aria-label', `View filters used for ${job.dashboard_name}`);
      filtersIcon.setAttribute('aria-describedby', 'ds-ppt-filter-tooltip');
      filtersIcon.setAttribute('aria-haspopup', 'dialog');
      filtersIcon.addEventListener('pointerenter', () => showDashboardPptJobFilterTooltip(filtersIcon, job));
      filtersIcon.addEventListener('pointerleave', hideDashboardPptFilterTooltip);
      filtersIcon.addEventListener('focus', () => showDashboardPptJobFilterTooltip(filtersIcon, job));
      filtersIcon.addEventListener('blur', hideDashboardPptFilterTooltip);
      filtersIcon.addEventListener('click', () => showDashboardPptJobFilters(job));
      filtersCell.dataset.filterValue = filterTooltip; filtersCell.append(filtersIcon); row.append(filtersCell);
      for (const value of [job.slides || '-', job.charts || '-']) row.append(node('td', String(value)));
      const statusCell = node('td');
      const badge = node('span', String(job.status || '').replaceAll('_', ' '), `queue-status-pill queue-status-${String(job.status || '').replaceAll('_', '-')}`);
      if (job.error) badge.title = job.error;
      statusCell.append(badge); row.append(statusCell);
      const progressCell = node('td');
      const progress = document.createElement('progress'); progress.max = 100; progress.value = Number(job.progress) || 0;
      const duration = Number(job.duration_seconds);
      const durationLabel = Number.isFinite(duration) ? ` · ${duration < 60 ? `${duration < 10 ? duration.toFixed(1) : Math.round(duration)}s` : `${Math.floor(duration / 60)}m ${Math.round(duration % 60)}s`}` : '';
      progressCell.append(progress, node('span', ` ${Number(job.progress) || 0}%${durationLabel}`)); row.append(progressCell);
      const actionsCell = node('td'); const actions = node('div', undefined, 'report-job-actions');
      if (job.download_url) { const link = node('a', '', 'report-job-download-button report-job-report-download-button'); link.href = job.download_url; link.download = ''; link.title = link.ariaLabel = 'Download Dashboard PPT'; actions.append(link); }
      if (job.charts_download_url) { const link = node('a', '', 'report-job-download-button report-job-charts-download-button'); link.href = job.charts_download_url; link.download = ''; link.title = link.ariaLabel = 'Download Dashboard charts as ZIP'; actions.append(link); }
      if (job.charts_api_url) actions.append(jobAction('Open Dashboard charts', 'report-job-charts-button', () => loadDashboardPptCharts(job.id, true), '📈'));
      if (job.retry_url) actions.append(jobAction(job.status === 'ready' ? 'Relaunch Job' : 'Retry export', 'report-job-retry-button', async () => { await api(`/ppt-jobs/${job.id}/retry`, 'POST'); await refreshDashboardPptJobs(); }, '↻'));
      if (job.stop_url) actions.append(jobAction('Stop export', 'report-job-stop-button', async () => { await api(`/ppt-jobs/${job.id}/stop`, 'POST'); await refreshDashboardPptJobs(); }, '■'));
      if (config.can_manage) actions.append(jobAction('Delete export', 'danger-button', async () => {
        if (!await window.showConfirmDialog(`Delete Dashboard PPT job ${job.id} and all its files?`, {title: 'Delete Dashboard PPT', confirmLabel: 'Delete'})) return;
        await api(`/ppt-jobs/${job.id}/delete`, 'POST'); await refreshDashboardPptJobs();
      }, '×'));
      actionsCell.append(actions); row.append(actionsCell); body.append(row);
    }
    syncDashboardPptChartJobs(jobs, preferredJobId);
    dashboardPptColumnFilters?.apply();
    if (!dashboardPptColumnFilters) syncDashboardPptJobsHeight();
  };
  function syncDashboardPptJobsHeight() {
    const body = $('ds-ppt-jobs-body');
    const wrapper = body.closest('.ds-ppt-jobs-table-wrap');
    if (!wrapper) return;
    const rows = Array.from(body.rows);
    rows.forEach((row) => { row.hidden = !(dashboardPptColumnFilters?.matches(row) ?? true); });
    const visibleRows = rows.filter(row => !row.hidden);
    requestAnimationFrame(() => {
      if (window.matchMedia('(max-width: 760px)').matches || visibleRows.length <= 5) {
        wrapper.style.maxHeight = '';
        return;
      }
      const table = wrapper.querySelector('.ds-ppt-jobs-table');
      const headerHeight = table?.tHead?.getBoundingClientRect().height || 0;
      const rowsHeight = visibleRows.slice(0, 5).reduce(
        (height, row) => height + row.getBoundingClientRect().height, 0,
      );
      wrapper.style.maxHeight = `${Math.ceil(headerHeight + rowsHeight + 2)}px`;
    });
  }
  const refreshDashboardPptJobs = async () => {
    if (dashboardPptJobsRefreshing) return;
    dashboardPptJobsRefreshing = true;
    try {
      const previousJobs = new Map(dashboardPptJobs.map(job => [String(job.id), job]));
      const payload = await api('/ppt-jobs');
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      const newlyReady = dashboardPptJobsLoaded ? jobs.filter(job => {
        const previous = previousJobs.get(String(job.id));
        return job.status === 'ready' && job.charts_api_url && (!previous || previous.status !== 'ready');
      }).sort((left, right) =>
        String(right.timestamp || '').localeCompare(String(left.timestamp || '')) || Number(right.id) - Number(left.id)) : [];
      renderDashboardPptJobs(jobs, newlyReady[0]?.id || '');
      dashboardPptJobsLoaded = true;
    } finally {
      dashboardPptJobsRefreshing = false;
    }
  };
  dashboardPptColumnFilters = window.enableExcelColumnFilters?.(
    $('ds-ppt-jobs-body').closest('table'), {onChange: syncDashboardPptJobsHeight},
  ) || null;
  if ($('ds-ppt-jobs-delete-all')) bind('ds-ppt-jobs-delete-all', async () => {
    const accepted = await window.showConfirmDialog(
      'Delete all Dashboard PPT jobs and every generated PPT and chart folder?',
      {title: 'Delete All PPTs', confirmLabel: 'Delete all', tone: 'danger'},
    );
    if (!accepted) return;
    await api('/ppt-jobs/delete-all', 'POST');
    await refreshDashboardPptJobs();
    status('All Dashboard PPT jobs and files were deleted.');
  });
  const setDashboardStatus = (id, state, label) => {
    if (!id) return;
    dashboardStatuses.set(id, {state, label});
    renderDashboardStatuses();
  };
  const refreshDashboardStatuses = async () => {
    if (dashboardStatusRefreshing) return;
    dashboardStatusRefreshing = true;
    try {
      const statusDefinitions = Object.fromEntries(Object.entries(dashboards).map(
        ([id, item]) => [id, runtimeDashboardDefinition(item, id)],
      ));
      const payload = await api('/statuses', 'POST', statusDefinitions);
      for (const [id, value] of Object.entries(payload || {})) {
        const activePrepared = id === activeId && Boolean(prepared?.slides?.length) && !dashboardNeedsRefresh();
        if (activePrepared) dashboardStatuses.set(id, {state: 'ready', label: 'Ready'});
        else if (!dashboardPreparationTokens.has(id)) dashboardStatuses.set(id, value);
      }
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
    const updateUnsavedState = () => updateFilterControlState(host, isUnsaved());
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
    definition.date_from = from === 'Oldest' ? 'Oldest' : !from || from < dateBounds.min || from > dateBounds.max ? dateBounds.min : from;
    definition.date_to = to === 'Newest' ? 'Newest' : !to || to < dateBounds.min || to > dateBounds.max ? dateBounds.max : to;
    return previous?.min !== dateBounds.min || previous?.max !== dateBounds.max || from !== definition.date_from || to !== definition.date_to;
  }
  const parseCalendarDate = value => /^\d{4}-\d{2}-\d{2}$/.test(String(value || '')) ? new Date(`${value}T00:00:00`) : null;
  const calendarDateValue = value => [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-');
  const calendarMonthValue = value => value.getFullYear() * 12 + value.getMonth();
  const dateInputDisplayValue = (key, value) => {
    if (value === 'Oldest') return dateBounds?.min ? `Oldest (${dateBounds.min})` : 'Oldest';
    if (value === 'Newest') return dateBounds?.max ? `Newest (${dateBounds.max})` : 'Newest';
    return value || '';
  };
  function datePicker(key, label) {
    const wrapper = node('div', undefined, 'ds-date-picker');
    updateFilterControlState(wrapper, dateState(key), true);
    const captionLabel = node('span', label, 'ds-date-picker-label');
    const input = document.createElement('input');
    input.type = 'text'; input.readOnly = true; input.value = dateInputDisplayValue(key, definition[key]); input.placeholder = 'Select date'; input.setAttribute('aria-label', label);
    const automaticLabel = key === 'date_from' ? 'Use oldest' : 'Use newest';
    const automaticValue = key === 'date_from' ? 'Oldest' : 'Newest';
    const automatic = node('button', automaticLabel, 'ds-date-auto-action'); automatic.type = 'button';
    automatic.setAttribute('aria-pressed', String(definition[key] === automaticValue));
    automatic.title = `${automaticLabel} date from the selected datasets`;
    if (eventTimeFilteringDisabled) {
      wrapper.classList.add('is-event-time-filtering-disabled');
      wrapper.title = eventTimeFilteringDisabledReason;
      wrapper.setAttribute('aria-label', `${label}. ${eventTimeFilteringDisabledReason}`);
      input.disabled = true;
      input.setAttribute('aria-disabled', 'true');
      automatic.disabled = true;
      automatic.setAttribute('aria-disabled', 'true');
      automatic.title = eventTimeFilteringDisabledReason;
    }
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
        button.addEventListener('click', () => { input.value = iso; definition[key] = iso; automatic.setAttribute('aria-pressed', 'false'); updateFilterControlState(wrapper, dateState(key), true); menu.hidden = true; filterChanged(); });
        days.append(button);
      }
    };
    previous.addEventListener('click', () => { month.setMonth(month.getMonth() - 1); render(); });
    next.addEventListener('click', () => { month.setMonth(month.getMonth() + 1); render(); });
    input.addEventListener('click', () => { menu.hidden = !menu.hidden; if (!menu.hidden) render(); });
    input.addEventListener('keydown', event => { if (event.key === 'Escape') menu.hidden = true; else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); menu.hidden = !menu.hidden; if (!menu.hidden) render(); } });
    document.addEventListener('pointerdown', event => { if (!wrapper.contains(event.target)) menu.hidden = true; });
    automatic.addEventListener('click', () => {
      definition[key] = automaticValue;
      input.value = dateInputDisplayValue(key, automaticValue);
      automatic.setAttribute('aria-pressed', 'true');
      updateFilterControlState(wrapper, dateState(key), true);
      filterChanged();
    });
    const control = node('div', undefined, 'ds-date-picker-control'); control.append(input, automatic);
    wrapper.append(captionLabel, control, menu); return wrapper;
  }
  function resetAutomaticDatesForDatasetChange() {
    if (!definition) return;
    if (!definition.date_from) definition.date_from = 'Oldest';
    if (!definition.date_to) definition.date_to = 'Newest';
  }
  function sources() {
    const host = $('ds-sources'); host.replaceChildren();
    for (const kind of ['data','voice','speech']) host.append(selectControl(`CDR ${kind[0].toUpperCase()+kind.slice(1)}`, config.datasets[kind].map(row => [String(row.id), `${row.file_name} · ${row.row_count} rows`]), definition.datasets[kind] || [], values => {
      resetAutomaticDatesForDatasetChange();
      definition.datasets[kind] = values.map(Number);
    }, true, () => sourceState(kind)));
    const scopeControl = $('ds-scope');
    scopeControl.value = definition.scope || 'single';
    updateFilterControlState(scopeControl.closest('.ds-scope-control'), scopeState());
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
      updateFilterControlState(facet, filterState(field));
      const selected = definition.filters[field];
      const custom = definition.custom_fields.includes(field);
      const label = custom ? field : field === 'technology_primary' ? 'Technology' : field.replaceAll('_',' ').replace(/\b\w/g, letter => letter.toUpperCase());
      const aliases = Object.entries(filterAliases).find(([name]) => identity(name) === identity(field))?.[1] || [];
      if (aliases.length > 1) {
        const aliasTooltip = `Supported columns by priority:\n${aliases.map((alias, index) => `${index + 1}. ${alias}`).join('\n')}`;
        facet.dataset.aliasTooltip = aliasTooltip;
        facet.tabIndex = 0;
        facet.setAttribute('aria-label', `${label} filter. ${aliasTooltip.replaceAll('\n', ' ')}`);
      }
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
      if (!available.length) { values.disabled = true; values.append(option('', facetsLoading || facetOptionRequests.has(field) ? 'Loading values…' : 'No matching values')); }
      values.onchange = () => {
        const next = [...values.selectedOptions].map(item => item.value).filter(Boolean);
        const current = (selected || available).filter(Boolean);
        if (next.length === current.length && next.every(value => current.includes(value))) return;
        definition.filters[field] = next;
        updateFilterControlState(facet, filterState(field));
        filterChanged();
      };
      facet.append(values);
      (custom ? additionalHost : defaultHost).append(facet);
    }
    if (!additionalHost.childElementCount) additionalHost.append(node('p', 'No additional filters have been added.', 'form-note ds-no-additional-filters'));
    const visible = [...fields].map(field => identity(field));
    const restorable = facetFields.filter(field => hidden.has(identity(field)));
    const choices = [...restorable, ...availableFields].filter((field, index, all) => (
      !visible.includes(identity(field))
      && all.findIndex(item => identity(item) === identity(field)) === index
    ));
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
  const preparedPayloadKey = (id, fingerprint) => `${id}:${fingerprint}`;
  const rememberPrepared = payload => {
    const fingerprint = preparedStateFingerprint(definition), entry = {payload, fingerprint};
    preparedPayloads.set(preparedPayloadKey(activeId, fingerprint), entry);
    try {
      const stored = JSON.parse(sessionStorage.getItem(preparedStorageKey) || 'null');
      const entries = Array.isArray(stored?.entries) ? stored.entries.filter(item => item?.fingerprint !== fingerprint) : [];
      entries.push({fingerprint, token: payload.token});
      sessionStorage.setItem(preparedStorageKey, JSON.stringify({dashboardId: activeId, entries: entries.slice(-8)}));
    } catch (_) { /* Session storage is optional. */ }
  };
  const forgetPreparedToken = token => {
    if (!token) return;
    for (const [key, entry] of preparedPayloads.entries()) {
      if (entry?.payload?.token === token) preparedPayloads.delete(key);
    }
    try {
      const stored = JSON.parse(sessionStorage.getItem(preparedStorageKey) || 'null');
      if (!stored) return;
      const entries = (stored.entries || []).filter(item => item?.token !== token);
      if (stored.token === token) delete stored.token;
      sessionStorage.setItem(preparedStorageKey, JSON.stringify({...stored, entries}));
    } catch (_) { /* Session storage is optional. */ }
  };
  const restoreRememberedPrepared = async id => {
    const fingerprint = preparedStateFingerprint(definition);
    const inMemory = preparedPayloads.get(preparedPayloadKey(id, fingerprint));
    if (inMemory?.fingerprint === fingerprint && inMemory.payload?.token) {
      try {
        const payload = await api(`/prepared/${encodeURIComponent(inMemory.payload.token)}`);
        if (activeId !== id || preparedStateFingerprint(definition) !== fingerprint) return false;
        applyPreparedPayload(payload);
        return true;
      } catch (error) {
        if (error.status !== 410 && !error.message.includes('expired')) return false;
        forgetPreparedToken(inMemory.payload.token);
      }
    }
    let stored;
    try { stored = JSON.parse(sessionStorage.getItem(preparedStorageKey) || 'null'); }
    catch (_) { return false; }
    const cachedEntry = stored?.dashboardId === id
      ? (stored.entries || []).find(item => item?.fingerprint === fingerprint) || (stored.fingerprint === fingerprint ? stored : null)
      : null;
    if (!cachedEntry?.token) return false;
    try {
      const payload = await api(`/prepared/${encodeURIComponent(cachedEntry.token)}`);
      if (activeId !== id || preparedStateFingerprint(definition) !== fingerprint) return false;
      applyPreparedPayload(payload);
      return true;
    } catch (error) {
      if (error.status !== 410 && !error.message.includes('expired')) return false;
      forgetPreparedToken(cachedEntry.token);
      return false;
    }
  };
  const forgetPrepared = () => {
    for (const key of preparedPayloads.keys()) if (key.startsWith(`${activeId}:`)) preparedPayloads.delete(key);
    try { sessionStorage.removeItem(preparedStorageKey); } catch (_) { /* Session storage is optional. */ }
  };
  const setPreparationRows = payload => {
    const rows = $('ds-preparing-rows');
    const formatCounts = counts => Object.entries(counts || {}).map(([kind, count]) => `${kind.toUpperCase()}: ${Number(count).toLocaleString()} rows`).join(' · ');
    const selectedUniverse = Object.fromEntries(['data', 'voice', 'speech'].map(kind => [kind,
      (config.datasets?.[kind] || []).filter(dataset => (definition?.datasets?.[kind] || []).includes(dataset.id))
        .reduce((total, dataset) => total + Number(dataset.row_count || 0), 0),
    ]));
    const universe = formatCounts(payload?.universe_rows || selectedUniverse);
    const filtered = formatCounts(payload?.rows);
    rows.replaceChildren();
    for (const [label, counts, className] of [
      ['Dataset Universe', universe, 'ds-preparing-universe-label'],
      ['Filtered Universe', filtered, 'ds-preparing-filtered-label'],
    ]) {
      if (!counts) continue;
      const line = node('span', undefined, 'ds-preparing-row');
      line.append(node('span', `${label}: `, `ds-preparing-row-label ${className}`), document.createTextNode(counts));
      rows.append(line);
    }
    rows.hidden = !rows.textContent;
  };
  const applyPreparedPayload = payload => {
    prepared = payload; facetOptions = payload.options; facetFields = config.filter_fields || payload.filter_fields || facetFields; availableFields = payload.available_fields || payload.custom_fields || []; applyDateBounds(payload.date_bounds); facetsLoading = false; facetOptionRequests.clear(); setPreparationProgress(100, 'Dashboard dataset is ready');
    appliedFilterState = preparationStateFingerprint(definition);
    appliedSelectionState = selectionStateFingerprint(definition);
    appliedDashboardDefinition = JSON.parse(JSON.stringify(definition));
    updateDirtyState();
    sources();
    if (hasOpenFacetMenu()) refreshFacetsAfterMenusClose(); else facets();
    setDashboardStatus(activeId, 'ready', 'Ready');
    setViewEnabled(Boolean(payload.slides?.length));
    setPreparationRows(payload);
    setPreparationState('ready');
    syncPreparationRefresh();
    chartPayloads.clear(); renderedChartPayloads.clear(); rememberPrepared(payload);
    if (!$('ds-viewer').hidden) renderSlide();
  };
  async function restorePrepared(id) {
    if (await restoreRememberedPrepared(id)) return true;
    try {
      // Send the active universe as well as the filters because both form
      // part of the shared persistent preview-cache identity.
      applyPreparedPayload(await api(`/prefetched/${encodeURIComponent(id)}`, 'POST', definition));
      return true;
    } catch (error) {
      // A queued warm-up must never delay opening the visible Dashboard.
      // Returning immediately lets its foreground preparation take priority.
      if (error.status === 409) return false;
      return false;
    }
  }
  function filterChanged() {
    rememberUniverse();
    updateDirtyState();
    const pendingFilters = hasUnappliedFilterChanges(), pendingUniverse = hasUnappliedUniverseChanges();
    status(pendingFilters && pendingUniverse
      ? 'Dataset Universe and filter changes are ready to apply.'
      : pendingUniverse
        ? 'Dataset Universe changes are ready to apply.'
        : pendingFilters
          ? 'Filter changes are ready to apply.'
          : 'All Dashboard filters and Dataset Universe controls are applied.');
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
    const requestedFilterState = preparationStateFingerprint(definition);
    // Universe changes need fresh filtered rows; Scope also changes how the
    // resulting charts group those rows by Operator or Vendor.
    const needsDataPreparation = selectionStateFingerprint(definition) !== appliedSelectionState;
    if (preparing) {
      if (preparingFilterState === requestedFilterState) return preparing;
      clearTimeout(timer); ++sequence; controller?.abort();
      try { await preparing; } catch (error) { if (error.name !== 'AbortError') throw error; }
      return prepare();
    }
    // Start the visible state before checking the shared cache.  Persistent
    // cache validation can take noticeable time after a server restart, and
    // the user must see that the Dashboard is working during that lookup.
    setViewEnabled(false);
    setPreparationState('preparing', needsDataPreparation ? 'data' : 'rendering');
    // This also checks the workspace-shared persistent manifest, so a user
    // selecting a universe already prepared by somebody else does not launch
    // a duplicate data-preparation request. The lookup itself can read a
    // manifest and validate its CDR revisions, so expose it immediately in
    // the global task card instead of leaving only the yellow viewer notice.
    const cacheLookupToken = backgroundPreparationToken = `cache-lookup-${++cacheLookupSequence}`;
    setPreparationProgress(null, 'Checking persistent Dashboard cache');
    emitPreparationStatus('processing', 'Checking persistent Dashboard cache', cacheLookupToken);
    if (await restorePrepared(activeId)) {
      if (backgroundPreparationToken === cacheLookupToken) dismissPreparationStatus();
      status('Restored the previously prepared filters.');
      return prepared;
    }
    if (backgroundPreparationToken === cacheLookupToken) dismissPreparationStatus();
    let preparationToken = '';
    let requestSequence = 0;
    const dashboardIdAtStart = activeId;
    const pending = (async () => {
    clearTimeout(timer); const current = requestSequence = ++sequence; controller?.abort(); controller = new AbortController();
    dismissPreparationStatus(); preparationToken = backgroundPreparationToken = `prepare-${current}`; preparingFilterState = preparationStateFingerprint(definition);
    dashboardPreparationTokens.set(dashboardIdAtStart, current);
    emitPreparationStatus(
      'queued',
      needsDataPreparation
        ? 'Submitting the Dashboard dataset preparation request'
        : 'Submitting the request to render Dashboard charts for the current scope',
      preparationToken,
    );
    setDashboardStatus(dashboardIdAtStart, needsDataPreparation ? 'loading-data' : 'rendering', needsDataPreparation ? 'Loading data' : 'Rendering');
    filterActionBusy = true; updateFilterActionState();
    facetsLoading = true;
    if (!hasOpenFacetMenu()) facets();
    setViewEnabled(false);
    setPreparationState('preparing', needsDataPreparation ? 'data' : 'rendering');
    $('ds-rows').textContent = '';
    try {
      const params = new URLSearchParams();
      if (activeId) params.set('dashboard_id', activeId);
      if (!needsDataPreparation) params.set('rendering_only', '1');
      params.set('preparation_id', preparationToken);
      // Dispatch the main request before polling its task id. This prevents a
      // progress request from occupying the connection while the preparation
      // request is still waiting in the browser's network queue.
      const preparationRequest = api(
        `/prepare${params.size ? `?${params}` : ''}`,'POST',definition,controller.signal,
      );
      monitorPreparationProgress(preparationToken);
      const payload = await preparationRequest;
      if (current !== sequence) return;
      applyPreparedPayload(payload);
      window.dispatchEvent(new Event('dashboard-analytic:refresh-background-tasks'));
    } catch (error) {
      if (current === sequence && error.name !== 'AbortError' && error.message.includes('interrupted')) {
        setDashboardStatus(dashboardIdAtStart, 'data-needed', 'Data needed'); facetsLoading = false; facets();
        setViewEnabled(false); setPreparationState('hidden'); status('Dashboard preparation was interrupted.'); return;
      }
      if (current === sequence && error.name !== 'AbortError') { setDashboardStatus(dashboardIdAtStart, 'error', 'Error'); facetsLoading = false; facets(); setViewEnabled(false); setPreparationState('hidden'); $('ds-rows').textContent = error.message; if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div',error.message,'ds-empty')); } throw error;
    }
    })();
    preparing = pending;
    try { return await pending; }
    finally {
      if (backgroundPreparationToken === preparationToken) dismissPreparationStatus();
      if (preparing === pending) { preparing = null; preparingFilterState = ''; }
      if (dashboardPreparationTokens.get(dashboardIdAtStart) === requestSequence) dashboardPreparationTokens.delete(dashboardIdAtStart);
      filterActionBusy = false; updateFilterActionState();
      syncDashboardPptActions();
      void refreshDashboardStatuses();
    }
  }
  async function openDashboard(id) {
    clearTimeout(facetsRefreshTimer);
    dismissPreparationStatus();
    clearTimeout(timer); ++sequence; controller?.abort(); preparing = null;
    stopPresentation();
    activeId = id; $('ds-viewer-export-ppt').dataset.dashboardPptId = id; definition = runtimeDashboardDefinition(dashboards[id], id); savedDefinition = definitionFingerprint(savedRuntimeDashboardDefinition(dashboards[id])); dirty = false; prepared = null; appliedFilterState = ''; appliedSelectionState = ''; appliedDashboardDefinition = null; facetOptions = {}; availableFields = []; facetOptionRequests.clear(); slideIndex = 0; setViewEnabled(false); rememberOpen(id);
    resetViewerForDashboard();
    $('ds-name').value = definition.name; setNrMode(definition.technology || definition.template_technology, definition.template);
    $('ds-filter-panel').hidden = false; document.dispatchEvent(new CustomEvent('page-panel-navigation:update')); setActiveDashboardHeading(definition.name); sources(); facets(); library(); status(''); await prepare();
    updateDirtyState();
    // Date defaults may be derived while the prepared payload is restored. Rebuild
    // the controls so their state agrees with the Apply and Save buttons.
    sources(); facets();
  }
  const filterDefinitionFields = ['filters', 'custom_fields', 'hidden_filters'];
  const universeDefinitionFields = ['scope', 'datasets', 'date_from', 'date_to'];
  const copyDefinitionFields = (target, source, fields) => {
    for (const field of fields) target[field] = structuredClone(source[field]);
    return target;
  };
  async function preparePart(part) {
    const draft = definition;
    const request = canonicalDashboardDefinition(structuredClone(draft));
    const fieldsToKeepApplied = part === 'filters' ? universeDefinitionFields : filterDefinitionFields;
    copyDefinitionFields(request, canonicalDashboardDefinition(appliedDefinition()), fieldsToKeepApplied);
    definition = request;
    try { return await prepare(); }
    finally {
      definition = draft;
      rememberUniverse();
      updateDirtyState();
      sources(); facets();
    }
  }
  async function savePart(part) {
    const isFilters = part === 'filters';
    if (!activeId || !definition || !(isFilters ? hasUnsavedFilterChanges() : hasUnsavedUniverseChanges())) return;
    if (!$('ds-filter-overlay').hidden) await closeFilters();
    filterActionBusy = true; updateFilterActionState();
    try {
      const dashboardId = activeId, draft = definition;
      const fields = isFilters ? filterDefinitionFields : universeDefinitionFields;
      const item = copyDefinitionFields(canonicalDashboardDefinition(savedDashboardDefinition()), draft, fields);
      item.name = $('ds-name').value.trim(); const result = await api(`/${dashboardId}`,'PUT',item);
      if (dashboardId !== activeId || draft !== definition) return;
      dashboards[dashboardId] = structuredClone(result.definition);
      const otherFields = isFilters ? universeDefinitionFields : filterDefinitionFields;
      definition = copyDefinitionFields(canonicalDashboardDefinition(result.definition), draft, otherFields);
      savedDefinition = definitionFingerprint(result.definition); rememberUniverse(); updateDirtyState(); sources(); facets(); library();
      if (isFilters ? hasUnappliedFilterChanges() : hasUnappliedUniverseChanges()) await preparePart(part);
      status(`Saved ${isFilters ? 'filters' : 'Dataset Universe'} for “${definition.name}”.`);
    } finally {
      filterActionBusy = false; updateFilterActionState();
    }
  }
  const save = () => savePart('filters');
  const confirmDiscard = async (ignoredFields = []) => !hasUnsavedDashboardChanges(ignoredFields) || await window.showConfirmDialog('Discard unsaved Dashboard changes?', {title:'Unsaved changes',confirmLabel:'Discard'});
  bind('ds-create', async () => {
    if (!await confirmDiscard(['name', 'template', 'template_technology', 'technology'])) return;
    const technology = $('ds-nr-mode').value;
    const selected = (config.templates[technology] || []).find(row => row.identifier === $('ds-template').value);
    if (!selected) throw new Error('Choose a template for the selected NR Mode.');
    const item = {name:$('ds-name').value.trim(),template_technology:technology,template:selected.name,technology,scope:'single',datasets:latestDatasetsForScope('single'),filters:{},custom_fields:[],date_from:'Oldest',date_to:'Newest'};
    status(`Creating “${item.name}”…`); $('ds-create').disabled = true;
    try { const id = dashboardId(), result = await api(`/${id}`,'PUT',item); dashboards[id] = result.definition; await openDashboard(id); }
    finally { $('ds-create').disabled = !$('ds-template').options.length; }
  });
  bind('ds-save', save);
  bind('ds-save-universe', () => savePart('universe'));
  bind('ds-reload-universe', () => {
    if (!definition || !hasUnsavedUniverseChanges()) return;
    copyDefinitionFields(definition, savedDashboardDefinition(), universeDefinitionFields);
    sources(); facets(); filterChanged();
  });
  bind('ds-apply-filters', async () => {
    if (!hasUnappliedFilterChanges()) return;
    if (!$('ds-filter-overlay').hidden) await closeFilters();
    await preparePart('filters');
  });
  bind('ds-apply-universe', async () => {
    if (!hasUnappliedUniverseChanges()) return;
    if (!$('ds-filter-overlay').hidden) await closeFilters();
    await preparePart('universe');
  });
  async function duplicateDashboard(sourceId) {
    const id = dashboardId(), item = runtimeDashboardDefinition(dashboards[sourceId]); item.name = nextName(`${item.name.slice(0,110)} (copy)`);
    status(`Duplicating “${dashboards[sourceId].name}”…`);
    const result = await api(`/${id}`,'PUT',item); dashboards[id] = result.definition; await openDashboard(id);
  }
  async function exportDashboard(id, item) {
    const response = await fetch(`/api/e2e-dashboards/${encodeURIComponent(id)}/export`, {credentials: 'same-origin'});
    if (!response.ok) throw new Error(await response.text() || 'Unable to export the Dashboard.');
    const blob = await response.blob(), url = URL.createObjectURL(blob), link = node('a');
    link.href = url; link.download = `${item.name.replace(/[^a-z0-9_-]/gi, '_')}_dashboard.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status(`Exported “${item.name}”.`);
  }
  async function deleteDashboard(id) {
    const item = dashboards[id]; if (!item || !await window.showConfirmDialog(`Delete “${item.name}”?`,{title:'Delete Dashboard',confirmLabel:'Delete',tone:'danger'})) return;
    if (id === activeId && !await confirmDiscard()) return;
    status(`Deleting “${item.name}”…`);
    await api(`/${id}`,'DELETE'); delete dashboards[id]; dashboardStatuses.delete(id); if (id === activeId) closeDashboard(); else { library(); status(`Deleted “${item.name}”.`); }
  }
  bind('ds-import',() => $('ds-import-file').click());
  $('ds-import-file').onchange = safe(async () => { const file = $('ds-import-file').files[0]; if (!file) return; const payload = JSON.parse(await file.text()); const legacy = payload.format === 'dashboard-analytic-dashboard-set' && payload.version === 1; if (!legacy && (payload.format !== 'dashboard-analytic-dashboard' || payload.version !== 2)) throw new Error('Unsupported Dashboard file.'); if (!await confirmDiscard()) return; payload.definition.name = nextName(payload.definition.name); const id = dashboardId(), result = await api(`/${id}`,'PUT',payload.definition); dashboards[id] = result.definition; await openDashboard(id); $('ds-import-file').value = ''; });
  function closeDashboard() { delete $('ds-viewer-export-ppt').dataset.dashboardPptId; $('ds-viewer-export-ppt').disabled = true; clearTimeout(facetsRefreshTimer); dismissPreparationStatus(); stopPresentation(); rememberOpen(''); ++sequence; clearTimeout(timer); controller?.abort(); preparing = null; activeId = ''; definition = null; savedDefinition = ''; appliedFilterState = ''; appliedSelectionState = ''; appliedDashboardDefinition = null; prepared = null; dirty = false; updateUnsavedFiltersBadge(); setViewEnabled(false); setPreparationState('hidden'); $('ds-filter-panel').hidden = true; document.dispatchEvent(new CustomEvent('page-panel-navigation:update')); setActiveDashboardHeading(''); $('ds-name').value = ''; setNrMode('nsa'); library(); status('Dashboard closed.'); }
  $('ds-name').oninput = () => { if (definition) { definition.name = $('ds-name').value; updateDirtyState(); } };
  $('ds-nr-mode').onchange = () => {
    const selected = setNrMode($('ds-nr-mode').value);
    if (definition && selected) { definition.template_technology = definition.technology = $('ds-nr-mode').value; definition.template = selected.name; changed(); }
  };
  $('ds-template').onchange = () => { if (definition) { setTemplate($('ds-template').value); changed(); } };
  $('ds-scope').onchange = safe(async () => {
    if (!definition) return;
    const selectedScope = $('ds-scope').value;
    if (selectedScope !== definition.scope) {
      definition.datasets = latestDatasetsForScope(selectedScope);
      definition.date_from = 'Oldest';
      definition.date_to = 'Newest';
    }
    definition.scope = selectedScope;
    sources();
    updateFilterControlState($('ds-scope').closest('.ds-scope-control'), scopeState());
    filterChanged();
  });
  bind('ds-add-filter', async () => {
    const field = $('ds-custom-field').value;
    if (!field) return;
    const defaultField = facetFields.find(item => identity(item) === identity(field));
    if (defaultField) definition.hidden_filters = definition.hidden_filters.filter(item => identity(item) !== identity(defaultField));
    else definition.custom_fields.push(field);
    const dashboardIdAtStart = activeId;
    const requestedState = selectionStateFingerprint(definition);
    const requestId = ++facetOptionRequestSequence;
    facetOptionRequests.set(field, requestId);
    facets(); filterChanged();
    try {
      const payload = await api('/filter-options', 'POST', {definition, field});
      if (activeId !== dashboardIdAtStart || selectionStateFingerprint(definition) !== requestedState || facetOptionRequests.get(field) !== requestId) return;
      facetOptions[field] = Array.isArray(payload.values) ? payload.values : [];
    } finally {
      if (facetOptionRequests.get(field) === requestId) {
        facetOptionRequests.delete(field);
        if (activeId === dashboardIdAtStart) facets();
      }
    }
  });
  bind('ds-clear-filters', () => { definition.filters = {}; facets(); filterChanged(); });
  bind('ds-last-saved-filters', () => {
    const saved = savedDashboardDefinition();
    const current = filterStateFingerprint(definition);
    definition.filters = structuredClone(saved.filters || {});
    definition.custom_fields = structuredClone(saved.custom_fields || []);
    definition.hidden_filters = structuredClone(saved.hidden_filters || []);
    const restored = filterStateFingerprint(definition);
    if (restored === current) return;
    facets(); filterChanged();
  });
  bind('ds-viewer-refresh', async () => {
    if (!prepared?.token) return;
    const accepted = await window.showConfirmDialog(
      'Invalidate the rendered chart cache and render every chart in this Dashboard again?',
      {title: 'Refresh Dashboard charts?', confirmLabel: 'Refresh Charts', tone: 'warning'},
    );
    if (!accepted) return;
    let token = prepared.token;
    const refreshButton = $('ds-viewer-refresh');
    refreshButton.disabled = true;
    setViewEnabled(false);
    setPreparationState('preparing', 'rendering');
    status('Rendering every Dashboard chart again…');
    try {
      try {
        await api(`/charts/${encodeURIComponent(token)}/refresh`, 'POST');
      } catch (error) {
        if (error.status !== 410 && !error.message.includes('expired')) throw error;
        status('Restoring the expired Dashboard preview…');
        forgetPreparedToken(token);
        prepared = null;
        if (!await restorePrepared(activeId)) await prepare();
        token = prepared?.token || '';
        if (!token) throw new Error('The Dashboard preview could not be restored. Reopen the Dashboard and try again.');
        await api(`/charts/${encodeURIComponent(token)}/refresh`, 'POST');
      }
      if (prepared?.token !== token) return;
      chartPayloads.clear();
      renderedChartPayloads.clear();
      setPreparationProgress(100, 'Dashboard charts are ready');
      renderSlide();
      status('Every Dashboard chart was rendered again.');
      void refreshDashboardStatuses();
    } finally {
      if (prepared?.token === token) {
        refreshButton.disabled = false;
        setViewEnabled(Boolean(prepared.slides?.length));
        setPreparationState('ready');
      }
    }
  });
  bind('ds-preparing-refresh', async () => {
    if (dashboardNeedsRefresh()) await prepare();
  });
  bind('ds-viewer-export-ppt', async () => {
    const item = dashboards[activeId];
    if (item) await queueDashboardPptExport(activeId, item);
  });
  bind('ds-generate-ppt', async () => {
    const item = dashboards[activeId];
    if (item) await queueDashboardPptExport(activeId, item);
  });
  bind('ds-view', openActiveDashboardViewer);
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
  const proximityIndexes = (length, origin) => {
    const indexes = [];
    for (let distance = 1; distance < length; distance += 1) {
      if (origin + distance < length) indexes.push(origin + distance);
      if (origin - distance >= 0) indexes.push(origin - distance);
    }
    return indexes;
  };
  const yieldForSilentPreload = () => new Promise(resolve => {
    if ('requestIdleCallback' in window) window.requestIdleCallback(() => resolve(), {timeout: 200});
    else window.setTimeout(resolve, 0);
  });
  function scheduleNearbySlidePreload(token, origin, visibleLoads = []) {
    const request = ++slidePreloadRequest;
    void Promise.allSettled(visibleLoads).then(async () => {
      await yieldForSilentPreload();
      const slides = prepared?.slides || [];
      for (const target of proximityIndexes(slides.length, origin)) {
        if (
          request !== slidePreloadRequest
          || prepared?.token !== token
          || $('ds-viewer').hidden
          || !$('ds-chart-expanded-overlay').hidden
        ) return;
        const charts = (slides[target]?.charts || []).filter(chart => chart.available);
        await Promise.allSettled(charts.map(chart => loadChartPayload(chart, 'low')));
        await yieldForSilentPreload();
      }
    });
  }
  function scheduleNearbyExpandedChartPreload(contextKey, chart) {
    const request = ++expandedChartPreloadRequest;
    if (expandedChartMode !== 'dashboard') return;
    const charts = expandedCharts();
    const origin = charts.findIndex(candidate => candidate.index === chart?.index);
    if (origin < 0) return;
    void (async () => {
      await yieldForSilentPreload();
      for (const target of proximityIndexes(charts.length, origin)) {
        if (
          request !== expandedChartPreloadRequest
          || expandedChartMode !== 'dashboard'
          || prepared?.token !== contextKey
          || expandedChart?.index !== chart.index
          || $('ds-chart-expanded-overlay').hidden
        ) return;
        await loadChartPayload(charts[target], 'low').catch(() => undefined);
        await yieldForSilentPreload();
      }
    })();
  }
  function dashboardViewerBrand(className = 'ds-structural-brand') {
    const brand = node('div', undefined, className);
    const mark = document.createElement('img'); mark.src = config.brand_mark; mark.alt = `${config.app_name || 'Dashboard Analytic'} logo`; mark.width = 72; mark.height = 72;
    brand.append(node('strong', config.app_name || 'Dashboard Analytic'), mark);
    return brand;
  }
  function structuralDashboard(stage, slide) {
    const kind = String(slide.structural_type || '').toLowerCase().includes('transition') ? 'transition' : 'title';
    const cover = node('section', undefined, `ds-structural-slide ds-structural-${kind}`);
    cover.setAttribute('aria-label', `${kind === 'transition' ? 'Transition' : 'Title'} dashboard: ${slide.title || 'Untitled'}`);
    const brand = dashboardViewerBrand();
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
    const reset = node('button', undefined, 'ds-chart-zoom-button ds-chart-zoom-reset'); reset.type = 'button'; reset.title = 'Reset zoom'; reset.setAttribute('aria-label', 'Reset zoom'); reset.append(zoomResetIcon());
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
  const chartPanDirections = ['left', 'right', 'up', 'down'];
  const chartPanPaths = {
    left: 'M15 5 8 12l7 7', right: 'm9 5 7 7-7 7',
    up: 'M5 15 12 8l7 7', down: 'm5 9 7 7 7-7',
  };
  const createChartPanButton = (direction, className) => {
    const button = node('button', undefined, className);
    button.type = 'button';
    button.title = `Move view ${direction}`;
    button.setAttribute('aria-label', `Move view ${direction}`);
    button.hidden = true;
    button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${chartPanPaths[direction]}"/></svg>`;
    return button;
  };
  const bindChartPanControls = (canvas, buttons) => {
    const sync = () => {
      const state = globalThis.getDashboardChartPanState?.(canvas) || {zoom: 1};
      const zoomed = Number(state.zoom) > 1;
      chartPanDirections.forEach(direction => {
        const button = buttons[direction];
        button.hidden = !zoomed;
        button.disabled = !zoomed || !state[`canPan${direction[0].toUpperCase()}${direction.slice(1)}`];
      });
    };
    chartPanDirections.forEach(direction => {
      buttons[direction].onclick = event => {
        event.stopPropagation();
        globalThis.panDashboardChart?.(canvas, direction);
        sync();
      };
    });
    canvas.addEventListener('dashboardchartzoom', sync);
    canvas.addEventListener('dashboardchartpan', sync);
    sync();
    return sync;
  };
  const expandedOverlayHost = $('ds-chart-expanded-overlay');
  expandedOverlayHost.classList.add('ds-overlay', 'e2e-dashboards');
  document.body.append(expandedOverlayHost);
  document.body.append($('ds-editor-overlay'));
  document.body.append($('ds-data-overlay'));
  const expandedZoom = chartZoomControls($('ds-chart-expanded-canvas'));
  $('ds-chart-expanded-zoom').append(expandedZoom);
  const expandedCanvasShell = $('ds-chart-expanded-canvas-shell');
  const expandedCanvas = $('ds-chart-expanded-canvas');
  const expandedPanUp = createChartPanButton('up', 'ds-chart-expanded-pan ds-chart-expanded-pan-up');
  expandedPanUp.id = 'ds-chart-expanded-pan-up';
  const expandedPanDown = createChartPanButton('down', 'ds-chart-expanded-pan ds-chart-expanded-pan-down');
  expandedPanDown.id = 'ds-chart-expanded-pan-down';
  expandedCanvas.after(expandedPanUp, expandedPanDown);
  bindChartPanControls(expandedCanvas, {
    left: $('ds-chart-expanded-pan-left'), right: $('ds-chart-expanded-pan-right'),
    up: expandedPanUp, down: expandedPanDown,
  });
  let expandedControlsTimer;
  let expandedTouchControlsTimer;
  let expandedFiltersCloseTimer;
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
  expandedCanvasShell.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch' || event.target.closest('.ds-chart-filter-panel')) return;
    clearTimeout(expandedTouchControlsTimer);
    expandedCanvasShell.classList.add('ds-touch-controls-visible');
    expandedTouchControlsTimer = setTimeout(() => {
      expandedCanvasShell.classList.remove('ds-touch-controls-visible');
      expandedTouchControlsTimer = null;
    }, 3000);
  });
  let expandedChart = null;
  let expandedChartMode = 'dashboard';
  let expandedChartFilterControls = null;
  let expandedChartFilterToken = '';
  let expandedChartFilterIndex = -1;
  let expandedChartFilterContextPath = '';
  const expandedTemplateUpdate = node('button', 'Update Template', 'danger-button');
  expandedTemplateUpdate.id = 'ds-chart-filter-update';
  expandedTemplateUpdate.hidden = true;
  $('ds-chart-filter-apply').before(expandedTemplateUpdate);
  const setExpandedChartFiltersOpen = open => {
    clearTimeout(expandedFiltersCloseTimer);
    expandedFiltersCloseTimer = null;
    $('ds-chart-filter-panel').classList.toggle('is-open', open);
    $('ds-chart-filter-toggle').setAttribute('aria-expanded', String(open));
    if (open) $('ds-chart-filter-fields').querySelector('input,select,button')?.focus();
  };
  const scheduleExpandedChartFiltersClose = () => {
    clearTimeout(expandedFiltersCloseTimer);
    expandedFiltersCloseTimer = setTimeout(() => {
      if (!$('ds-chart-filter-panel').matches(':hover')) {
        setExpandedChartFiltersOpen(false);
        $('ds-chart-filter-toggle').focus();
      }
    }, 5000);
  };
  $('ds-chart-filter-panel').addEventListener('pointerenter', () => clearTimeout(expandedFiltersCloseTimer));
  $('ds-chart-filter-panel').addEventListener('pointerleave', scheduleExpandedChartFiltersClose);
  $('ds-chart-filter-panel').addEventListener('focusin', () => clearTimeout(expandedFiltersCloseTimer));
  // Focus can temporarily move from a panel field to one of its searchable
  // menus. Only leaving with the pointer starts the delayed auto-collapse;
  // a click outside the panel remains an immediate close below.
  document.addEventListener('pointerdown', event => {
    const panel = $('ds-chart-filter-panel');
    if (!panel.classList.contains('is-open') || panel.contains(event.target)) return;
    // Searchable selector menus are temporarily mounted in the overlay, not
    // inside the panel, and must remain interactive until a choice is made.
    if (event.target.closest('.report-chart-preview-select-menu')) return;
    setExpandedChartFiltersOpen(false);
  });
  const createExpandedChartFilterControls = context => {
    const sourceKey = source => {
      const normalized = String(source || '').trim().toLocaleLowerCase();
      return ({data: 'cdr-data', voice: 'cdr-voice', speech: 'cdr-speech'})[normalized]
        || (normalized.startsWith('cdr-') ? normalized : `cdr-${normalized}`);
    };
    const columnsBySource = context.columns_by_source || {[sourceKey(context.cdr_source)]: context.columns || []};
    return globalThis.createInteractiveChartPreviewControls($('ds-chart-filter-fields'), context, {
      columnsBySource, datasetsBySource: context.datasets_by_source || {},
      fields: [
        ['chart_type', 'Chart Type'], ['chart_title', 'Chart Title'], ['cdr_source', 'CDR Type'], ['dataset_ids', 'Datasets'],
        ['kpi', 'KPI'], ['filters', 'Filters'], ['grouping_rows', 'Rows'], ['grouping_columns', 'Columns'],
        ['legend', 'Legend'], ['legend_position', 'Legend Position'],
      ],
      textFields: {chart_title: true}, editableGroupingInputs: true,
      chartTypes: ['100% Stacked Vertical Bars', 'Count Stacked Horizontal Bars', 'CDF Line', 'Multi KPI CDF Lines', 'Scatter', 'Table', 'Distribution Stacked Vertical Bars', 'Threshold Stacked Vertical Bars', 'Average Vertical Bars', 'Median Vertical Bars', 'Map'],
      menuContainer: expandedOverlayHost,
      onSourceChange: next => {
        const source = sourceKey(next.cdr_source);
        expandedChartFilterControls = createExpandedChartFilterControls({...context, ...next, columns: columnsBySource[source] || []});
      },
    });
  };
  const loadExpandedChartFilters = async () => {
    const fields = $('ds-chart-filter-fields');
    if ((!prepared?.token && expandedChartMode !== 'ppt') || !expandedChart) return;
    const chart = expandedChart;
    fields.textContent = 'Loading filters…';
    expandedChartFilterContextPath = expandedChartMode === 'ppt'
      ? `/ppt-jobs/${encodeURIComponent(dashboardPptChartsJobId)}/charts/${chart.index}/filter-context`
      : `/chart/${encodeURIComponent(prepared.token)}/${chart.index}/filter-context`;
    const context = await api(expandedChartFilterContextPath);
    if (chart !== expandedChart) return;
    expandedChartFilterToken = String(context.token || prepared?.token || '');
    expandedChartFilterIndex = Number.isInteger(context.chart_index) ? context.chart_index : chart.index;
    expandedChartFilterControls = createExpandedChartFilterControls(context);
    expandedTemplateUpdate.hidden = !context.template_available;
  };
  $('ds-chart-filter-toggle').onclick = safe(async () => {
    const open = !$('ds-chart-filter-panel').classList.contains('is-open');
    setExpandedChartFiltersOpen(open);
    if (open && !expandedChartFilterControls) await loadExpandedChartFilters();
  });
  $('ds-chart-filter-close').onclick = () => setExpandedChartFiltersOpen(false);
  const renderExpandedChartDefinition = async ({closePanel = true} = {}) => {
    const chart = expandedChart;
    if (!chart || !expandedChartFilterControls) return null;
    const canvas = $('ds-chart-expanded-canvas');
    const message = $('ds-chart-expanded-message');
    const previewDefinition = expandedChartFilterControls.definition();
    message.textContent = 'Rendering chart preview…';
    message.hidden = false;
    try {
      if (!expandedChartFilterToken && expandedChartMode === 'ppt') {
        const preparedContext = await api(`${expandedChartFilterContextPath}?prepare=true`);
        expandedChartFilterToken = String(preparedContext.token || '');
        expandedChartFilterIndex = Number(preparedContext.chart_index);
      }
      if (!expandedChartFilterToken) throw new Error('The chart dataset could not be restored.');
      const payload = await api(`/chart/${encodeURIComponent(expandedChartFilterToken)}/${expandedChartFilterIndex}/filter-preview`, 'POST', previewDefinition);
      if (chart !== expandedChart) return null;
      setExpandedChartHeader({...chart, chart_type: previewDefinition.chart_type, cdr_source: previewDefinition.cdr_source}, payload.title);
      expandedZoom.reset();
      canvas.hidden = false;
      globalThis.renderDashboardChart(canvas, payload);
      message.hidden = true;
      if (closePanel) setExpandedChartFiltersOpen(false);
      return {previewDefinition, payload};
    } catch (error) {
      message.hidden = true;
      throw error;
    }
  };
  expandedTemplateUpdate.onclick = safe(async () => {
    if (!expandedChart || !expandedChartFilterControls) return;
    const accepted = await window.showConfirmDialog(
      'Render the current Chart Definition and update its Report Template row?',
      {title: 'Update Template?', confirmLabel: 'Update Template', tone: 'warning'},
    );
    if (!accepted) return;
    expandedTemplateUpdate.disabled = true;
    expandedTemplateUpdate.textContent = 'Rendering…';
    try {
      const rendered = await renderExpandedChartDefinition({closePanel: false});
      if (!rendered) return;
      expandedTemplateUpdate.textContent = 'Updating…';
      await api(`/chart/${encodeURIComponent(expandedChartFilterToken)}/${expandedChartFilterIndex}/update-template`, 'POST', rendered.previewDefinition);
      setExpandedChartFiltersOpen(false);
      window.showInfoDialog('The current Chart Definition values were saved to the Report Template.', {title: 'Template updated'});
    } finally {
      expandedTemplateUpdate.disabled = false;
      expandedTemplateUpdate.textContent = 'Update Template';
    }
  });
  $('ds-chart-filter-apply').onclick = safe(async () => {
    const chart = expandedChart;
    if (!chart || !expandedChartFilterControls) return;
    const button = $('ds-chart-filter-apply');
    button.disabled = true;
    button.textContent = 'Applying…';
    try {
      await renderExpandedChartDefinition();
    } finally {
      button.disabled = false;
      button.textContent = 'Apply';
    }
  });
  async function openChartDataset(chart) {
    dataToken = expandedChartMode === 'ppt' ? `ppt:${dashboardPptChartsJobId}` : prepared.token;
    dataEndpoint = expandedChartMode === 'ppt' ? String(chart.data_url || '') : `/data/${prepared.token}/${chart.index}`;
    if (!dataEndpoint) return;
    window.showLoadingOverlay('Loading Filtered Dataset', 'Please wait while the filtered dataset is prepared.');
    try {
      await renderData();
      overlay('ds-data-overlay', true);
    } catch (error) {
      overlay('ds-data-overlay', false);
      throw error;
    } finally {
      window.hideLoadingOverlay();
    }
  }
  $('ds-chart-expanded-data').onclick = safe(async () => { if (expandedChart) await openChartDataset(expandedChart); });
  const expandedCharts = () => expandedChartMode === 'ppt'
    ? dashboardPptCharts
    : prepared?.slides.flatMap(slide => slide.charts).filter(chart => chart.available) || [];
  const expandedChartSlide = chart => expandedChartMode === 'ppt'
    ? {number: chart?.slide}
    : prepared?.slides.find(slide => slide.charts.some(item => item.index === chart?.index));
  const expandedChartSourceLabel = chart => {
    const source = String(chart?.cdr_source || chart?.source || '').trim();
    if (!source) return '';
    if (/^cdr-/i.test(source)) return `CDR-${source.slice(4)}`;
    return `CDR-${source.charAt(0).toUpperCase()}${source.slice(1)}`;
  };
  const setExpandedChartHeader = (chart, title = '') => {
    const slide = expandedChartSlide(chart);
    const chartTitle = String(title || chart?.title || 'Expanded chart');
    $('ds-chart-expanded-title').textContent = slide?.number ? `Slide ${slide.number} · ${chartTitle}` : chartTitle;
    $('ds-chart-expanded-meta').textContent = [expandedChartSourceLabel(chart), chart?.chart_type]
      .filter(Boolean).join(' · ');
  };
  const syncExpandedChartNavigation = () => {
    const charts = expandedCharts();
    const index = charts.findIndex(chart => chart.index === expandedChart?.index);
    $('ds-chart-expanded-position').textContent = index < 0 ? 'Chart —' : `Chart ${index + 1} / ${charts.length}`;
    $('ds-chart-expanded-first').disabled = $('ds-chart-expanded-prev').disabled = index <= 0;
    $('ds-chart-expanded-next').disabled = $('ds-chart-expanded-last').disabled = index < 0 || index >= charts.length - 1;
  };
  const navigateExpandedChart = async target => {
    const mode = expandedChartMode;
    const charts = expandedCharts();
    const current = charts.findIndex(chart => chart.index === expandedChart?.index);
    if (current < 0 || target < 0 || target >= charts.length || target === current) return;
    if (mode === 'ppt') await showDashboardPptChart(target);
    else await openExpandedChart(charts[target]);
  };
  $('ds-chart-expanded-first').onclick = safe(async () => navigateExpandedChart(0));
  $('ds-chart-expanded-prev').onclick = safe(async () => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) - 1));
  $('ds-chart-expanded-next').onclick = safe(async () => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) + 1));
  $('ds-chart-expanded-last').onclick = safe(async () => navigateExpandedChart(expandedCharts().length - 1));
  const openFloatingFilters = () => { const panel = $('ds-filter-panel'); panel.open = true; panel.querySelector('summary').tabIndex = -1; $('ds-filter-float').append(panel); setPreparationState($('ds-preparing').dataset.state || 'hidden'); $('ds-view').hidden = false; $('ds-filter-close-action').hidden = false; overlay('ds-filter-overlay', true); };
  const closeFilters = async () => {
    const panel = $('ds-filter-panel'); panel.querySelector('summary').removeAttribute('tabindex'); $('ds-filter-home').append(panel); setPreparationState($('ds-preparing').dataset.state || 'hidden'); $('ds-view').hidden = false; $('ds-filter-close-action').hidden = true; overlay('ds-filter-overlay', false);
    return true;
  };
  const templateEditorHasUnsavedChanges = () => {
    try {
      return Boolean($('ds-editor-frame').contentDocument?.querySelector('[data-catalogue-editor]')?.hasUnsavedCatalogueChanges?.());
    } catch (_error) {
      return false;
    }
  };
  const templateEditorBaseUrl = (sourceDefinition = definition) => sourceDefinition
    ? `/admin/report-templates/${encodeURIComponent(sourceDefinition.template_technology)}/${encodeURIComponent(sourceDefinition.template)}/editor`
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
    if (templateChanged && expandedChartMode !== 'ppt') await prepare();
    return true;
  };
  const openTemplateEditor = (focusRow, sourceDefinition = definition) => {
    if (!sourceDefinition || !Number.isInteger(focusRow)) return;
    templateEditorSaved = false;
    const frame = $('ds-editor-frame');
    const url = templateEditorBaseUrl(sourceDefinition);
    if (frame.dataset.editorUrl === url) {
      focusTemplateEditorRow(focusRow);
    } else {
      frame.dataset.editorUrl = url;
      frame.dataset.editorFocusRow = String(focusRow);
      frame.src = `${url}?focus_row=${focusRow}`;
    }
    overlay('ds-editor-overlay', true);
  };
  $('ds-chart-expanded-refresh').onclick = safe(async () => {
    if (expandedChartMode === 'ppt') {
      const index = dashboardPptCharts.findIndex(chart => chart.index === expandedChart?.index);
      if (index >= 0) await showDashboardPptChart(index);
      return;
    }
    if (!expandedChart || !prepared?.token) return;
    const refreshButton = $('ds-chart-expanded-refresh');
    const chart = expandedChart;
    const token = prepared.token;
    const request = expandedChartRequest;
    const url = `/api/e2e-dashboards/chart/${token}/${chart.index}`;
    refreshButton.disabled = true;
    status(`Rendering ${chart.title || 'chart'} again…`);
    try {
      const payload = await api(`/chart/${encodeURIComponent(token)}/${chart.index}/refresh`, 'POST');
      if (prepared?.token !== token || expandedChartRequest !== request || $('ds-chart-expanded-overlay').hidden) return;
      chartPayloads.delete(url);
      renderedChartPayloads.set(url, payload);
      renderSlide();
      await openExpandedChart(chart, payload);
      status(`${chart.title || 'Chart'} was rendered again.`);
    } finally {
      refreshButton.disabled = false;
    }
  });
  $('ds-chart-expanded-filters').onclick = openFloatingFilters;
  $('ds-chart-expanded-auto-fields')?.addEventListener('click', () => document.querySelector('.ds-viewer-panel [data-workspace-manage-calculated-dimensions]')?.click());
  $('ds-chart-expanded-edit')?.addEventListener('click', () => {
    const job = expandedChartMode === 'ppt' ? selectedDashboardPptChartJob() : null;
    const sourceDefinition = job ? {
      template: job.template,
      template_technology: String(job.nr_mode || 'nsa').toLocaleLowerCase(),
    } : definition;
    openTemplateEditor(expandedChart?.focus_row, sourceDefinition);
  });
  function expandedChartOverlay(show) {
    const overlay = $('ds-chart-expanded-overlay');
    if (show) {
      slidePreloadRequest += 1;
      focusReturn.set('ds-chart-expanded-overlay', document.activeElement);
      overlay.hidden = false;
      overlay.querySelector('[role=dialog]').focus();
    } else {
      expandedChartRequest += 1;
      expandedChartPreloadRequest += 1;
      expandedChart = null;
      expandedChartMode = 'dashboard';
      overlay.hidden = true;
      $('ds-chart-expanded-canvas').hidden = true;
      focusReturn.get('ds-chart-expanded-overlay')?.focus();
      if (!$('ds-viewer').hidden && prepared?.token) {
        scheduleNearbySlidePreload(prepared.token, slideIndex);
      }
    }
    document.body.style.overflow = [...document.querySelectorAll('.ds-overlay')].some(item => !item.hidden) ? 'hidden' : '';
  }
  $('ds-chart-expanded-overlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) expandedChartOverlay(false);
  });
  async function openExpandedChart(chart, renderedPayload = null, mode = 'dashboard') {
    stopPresentation();
    const request = ++expandedChartRequest;
    const contextKey = mode === 'ppt' ? dashboardPptChartsJobId : prepared?.token;
    const canvas = $('ds-chart-expanded-canvas');
    const message = $('ds-chart-expanded-message');
    expandedChart = chart;
    expandedChartMode = mode;
    expandedChartFilterControls = null;
    expandedChartFilterToken = '';
    expandedChartFilterIndex = -1;
    expandedChartFilterContextPath = '';
    $('ds-chart-filter-fields').replaceChildren();
    expandedTemplateUpdate.hidden = true;
    setExpandedChartFiltersOpen(false);
    syncExpandedChartNavigation();
    const historical = mode === 'ppt';
    $('ds-chart-expanded-data').disabled = historical ? !chart.data_url : false;
    $('ds-chart-expanded-filters').hidden = historical;
    $('ds-chart-expanded-filters').disabled = false;
    $('ds-chart-expanded-auto-fields') && ($('ds-chart-expanded-auto-fields').disabled = false);
    if ($('ds-chart-expanded-edit')) $('ds-chart-expanded-edit').disabled = !Number.isInteger(chart.focus_row);
    $('ds-chart-expanded-data').title = historical && !chart.data_url ? 'Filtered dataset is unavailable for this earlier PowerPoint Job' : 'View dataset';
    $('ds-chart-expanded-filters').title = 'Adaptative Filters';
    expandedZoom.reset(); expandedZoom.hidden = true;
    const initialTitle = renderedPayload?.title || chart.title || 'Expanded chart';
    setExpandedChartHeader(chart, initialTitle);
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
    const currentContextKey = () => expandedChartMode === 'ppt' ? dashboardPptChartsJobId : prepared?.token;
    if (request !== expandedChartRequest || contextKey !== currentContextKey() || $('ds-chart-expanded-overlay').hidden) return;
    const title = payload?.title || chart.title || 'Expanded chart';
    setExpandedChartHeader(chart, title);
    canvas.setAttribute('aria-label', title);
    canvas.hidden = false;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (request !== expandedChartRequest || contextKey !== currentContextKey() || $('ds-chart-expanded-overlay').hidden) return;
    try {
      globalThis.renderDashboardChart(canvas, payload);
      expandedZoom.hidden = false;
      message.hidden = true;
      scheduleNearbyExpandedChartPreload(contextKey, chart);
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
    const panel = list.closest('.ds-slide-comments');
    panel?.classList.toggle('ds-has-comments', comments.length > 0);
    if (panel && presentation.active) panel.open = presentation.showComments && comments.length > 0;
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
    $('ds-viewer').classList.toggle('ds-presentation-active', presentation.active);
    $('ds-viewer').classList.toggle('ds-presentation-comments-enabled', presentation.active && presentation.showComments);
    button.classList.toggle('is-running', presentation.running);
    const action = presentation.active ? (presentation.running ? 'Pause presentation' : 'Resume presentation') : 'Presentation';
    button.title = action;
    button.setAttribute('aria-label', action);
    $('ds-presentation-start').disabled = presentation.active;
    $('ds-presentation-stop').disabled = !presentation.active;
    $('ds-presentation-stop-viewer').hidden = !presentation.active;
  }
  function stopPresentation() {
    clearTimeout(presentationTimer); presentationTimer = 0;
    if (!presentation.active) return;
    presentation.active = false; presentation.running = false; syncPresentationControls();
    const commentsPanel = $('ds-comments-list')?.closest('.ds-slide-comments');
    if (commentsPanel) commentsPanel.open = presentationCommentsWasOpen;
    status('Presentation stopped.');
  }
  function pausePresentation() {
    if (!presentation.active || !presentation.running) return;
    clearTimeout(presentationTimer); presentationTimer = 0;
    presentation.running = false; syncPresentationControls(); status('Presentation paused.');
  }
  function resumePresentation() {
    if (!presentation.active || presentation.running) return;
    presentation.running = true; syncPresentationControls(); schedulePresentationAdvance(); status('Presentation resumed.');
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
    const requestedDelay = Number($('ds-presentation-delay').value);
    const delaySeconds = Math.max(1, Math.min(300, Number.isFinite(requestedDelay) ? requestedDelay : 5));
    $('ds-presentation-delay').value = String(delaySeconds);
    presentation.delay = delaySeconds * 1000;
    const requestedTransitionDuration = Number($('ds-presentation-transition-duration').value);
    presentation.transitionDuration = Math.max(0.1, Math.min(10, Number.isFinite(requestedTransitionDuration) ? requestedTransitionDuration : 1));
    $('ds-presentation-transition-duration').value = String(presentation.transitionDuration);
    $('ds-viewer').style.setProperty('--ds-presentation-transition-duration', `${presentation.transitionDuration}s`);
    presentation.effect = $('ds-presentation-effect').value;
    presentation.showComments = $('ds-presentation-comments').value === 'yes';
    presentationCommentsWasOpen = Boolean($('ds-comments-list')?.closest('.ds-slide-comments')?.open);
    lastRandomPresentationEffect = '';
    slideIndex = 0;
    presentation.active = true; presentation.running = true; syncPresentationControls(); overlay('ds-presentation-overlay', false); renderSlide();
    $('ds-viewer').querySelector('.ds-viewer-panel')?.focus({preventScroll:true});
    schedulePresentationAdvance(); status(`Presentation started: ${presentation.delay / 1000} seconds per slide, ${presentation.transitionDuration} second transition.`);
  }
  function navigatePresentationSlide(offset) {
    const nextIndex = Math.max(0, Math.min(slideIndex + offset, (prepared?.slides.length || 1) - 1));
    if (nextIndex === slideIndex) return;
    slideIndex = nextIndex; renderSlide();
    if (presentation.running) schedulePresentationAdvance();
  }
  function presentationTransitionEffect() {
    if (presentation.effect !== 'random') return presentation.effect;
    const choices = randomPresentationEffects.filter(effect => effect !== lastRandomPresentationEffect);
    lastRandomPresentationEffect = choices[Math.floor(Math.random() * choices.length)] || 'fade';
    return lastRandomPresentationEffect;
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
    const preloadToken = prepared.token;
    const preloadOrigin = slideIndex;
    const visibleLoads = [];
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
      const brand = dashboardViewerBrand('ds-chart-brand'); card.append(brand);
      let renderedPayload = null;
      if (chart.position) {
        const [left,top,width,height] = chart.position;
        Object.assign(card.style,{left:`${left}%`,top:`${top}%`,width:`${width}%`,height:`${height}%`});
        card.style.setProperty('--ds-chart-left', `${left}%`);
        card.style.setProperty('--ds-chart-top', `${top}%`);
        card.style.setProperty('--ds-chart-width', `${width}%`);
        card.style.setProperty('--ds-chart-height', `${height}%`);
      }
      const message = node('div',`Rendering ${chart.title || 'chart'}…`,'ds-chart-message'); card.append(message);
      const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', chart.title); canvas.hidden = true; card.append(canvas);
      canvas.addEventListener('dashboardchartlayout', event => {
        const top = Number(event.detail?.titleTop);
        const height = Number(event.detail?.titleHeight);
        if (Number.isFinite(top) && Number.isFinite(height)) brand.style.top = `${top + height / 2}px`;
      });
      const zoom = chartZoomControls(canvas); card.append(zoom);
      const panButtons = Object.fromEntries(chartPanDirections.map(direction => [
        direction, createChartPanButton(direction, `ds-chart-pan-button ds-chart-pan-${direction}`),
      ]));
      Object.values(panButtons).forEach(button => card.append(button));
      bindChartPanControls(canvas, panButtons);
      if (chart.available) {
        const token = prepared.token;
        const chartLoad = loadChartPayload(chart);
        visibleLoads.push(chartLoad);
        chartLoad.then(payload => {
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
      } else message.textContent = chart.source
        ? `No CDR ${chart.source[0].toUpperCase()}${chart.source.slice(1)} dataset has been selected for this chart.`
        : 'No compatible CDR dataset has been selected for this chart.';
      const data = node('button','', 'ds-chart-data'); data.type = 'button'; data.title = 'View dataset'; data.setAttribute('aria-label', 'View dataset'); data.disabled = !chart.available; data.onclick = safe(async () => { await openChartDataset(chart); });
      const expand = node('button', '', 'ds-chart-expand'); expand.type = 'button'; expand.title = 'Expand chart'; expand.setAttribute('aria-label', 'Expand chart'); expand.disabled = !chart.available; expand.onclick = safe(async event => { event.stopPropagation(); await openExpandedChart(chart, renderedPayload); });
      card.ondblclick = safe(async event => {
        if (!chart.available || event.target.closest('button, a, input, select, label')) return;
        await openExpandedChart(chart, renderedPayload);
      });
      const controls = node('div', undefined, 'ds-chart-controls'); controls.append(data, expand, zoom); card.append(controls);
      let hideTimer;
      let touchControlsTimer;
      const showControls = () => { clearTimeout(hideTimer); hideTimer = null; card.classList.add('ds-hover'); };
      const hideControls = () => { if (!hideTimer) hideTimer = setTimeout(() => { card.classList.remove('ds-hover'); hideTimer = null; }, 500); };
      card.onpointerenter = showControls;
      card.onpointerleave = hideControls;
      card.onfocusin = showControls;
      card.onfocusout = () => { if (!card.contains(document.activeElement)) hideControls(); };
      card.addEventListener('pointerdown', event => {
        if (event.pointerType !== 'touch') return;
        clearTimeout(touchControlsTimer);
        card.classList.add('ds-touch-controls-visible');
        touchControlsTimer = setTimeout(() => {
          card.classList.remove('ds-touch-controls-visible');
          touchControlsTimer = null;
        }, 3000);
      });
      stage.append(card);
    }
    if (presentation.active) { stage.dataset.presentationEffect = presentationTransitionEffect(); void stage.offsetWidth; stage.classList.add('ds-slide-transition'); }
    renderComments();
    scheduleNearbySlidePreload(preloadToken, preloadOrigin, visibleLoads);
  }
  bind('ds-first',()=>{ stopPresentation(); slideIndex = 0; renderSlide(); });
  bind('ds-prev',()=>{ stopPresentation(); slideIndex--; renderSlide(); });
  bind('ds-next',()=>{ stopPresentation(); slideIndex++; renderSlide(); });
  bind('ds-last',()=>{ stopPresentation(); slideIndex = Math.max(0, (prepared?.slides.length || 1) - 1); renderSlide(); });
  const bindHorizontalSwipe = (host, {previous, next, blocked = () => false}) => {
    let gesture = null;
    const reset = () => { gesture = null; };
    host.addEventListener('pointerdown', event => {
      if (event.pointerType !== 'touch' || !event.isPrimary || blocked()) return;
      if (event.target.closest('button,a,input,select,textarea,summary,[contenteditable="true"],.multiselect-menu,.ds-chart-filter-panel')) return;
      const canvas = event.target.closest('canvas');
      if (canvas && Number(globalThis.getDashboardChartZoom?.(canvas) || 1) > 1) return;
      gesture = {pointerId: event.pointerId, x: event.clientX, y: event.clientY, time: performance.now()};
    });
    host.addEventListener('pointerup', event => {
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      const current = gesture;
      reset();
      const horizontal = event.clientX - current.x;
      const vertical = event.clientY - current.y;
      if (performance.now() - current.time > 900 || Math.abs(horizontal) < 56 || Math.abs(horizontal) < Math.abs(vertical) * 1.35) return;
      event.preventDefault();
      if (horizontal < 0) next();
      else previous();
    });
    host.addEventListener('pointercancel', reset);
  };
  bindHorizontalSwipe($('ds-viewer'), {
    blocked: () => $('ds-viewer').hidden || !prepared?.slides?.length,
    previous: () => {
      if (slideIndex <= 0) return;
      if (presentation.active) navigatePresentationSlide(-1);
      else { slideIndex -= 1; renderSlide(); }
    },
    next: () => {
      if (slideIndex >= (prepared?.slides.length || 1) - 1) return;
      if (presentation.active) navigatePresentationSlide(1);
      else { slideIndex += 1; renderSlide(); }
    },
  });
  bindHorizontalSwipe($('ds-chart-expanded-overlay'), {
    blocked: () => $('ds-chart-expanded-overlay').hidden || !expandedChart,
    previous: () => void safe(() => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) - 1))(),
    next: () => void safe(() => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) + 1))(),
  });
  $('ds-slide').onchange = () => { stopPresentation(); slideIndex = Number($('ds-slide').value); renderSlide(); };
  bind('ds-comment-add', async () => { const input = $('ds-comment-input'), comment = input.value.trim(); if (!comment || !definition) return; const key = currentSlideCommentKey(); definition.slide_comments ||= {}; const comments = definition.slide_comments[key] ||= []; if (comments.length >= 50) throw new Error('A slide can have at most 50 comments.'); comments.push(comment); input.value = ''; await persistComments(); renderComments(); });
  $('ds-comment-input').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); $('ds-comment-add').click(); } });
  bind('ds-presentation', () => {
    if (!presentation.active) overlay('ds-presentation-overlay', true);
    else if (presentation.running) pausePresentation();
    else resumePresentation();
  });
  bind('ds-presentation-close', () => overlay('ds-presentation-overlay', false));
  $('ds-presentation-effect').addEventListener('change', event => {
    try { localStorage.setItem(presentationEffectStorageKey, event.target.value); } catch (_) { /* Local storage is optional. */ }
  });
  bind('ds-presentation-start', startPresentation);
  bind('ds-presentation-stop', stopPresentation);
  bind('ds-presentation-stop-viewer', stopPresentation);
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
  closeOnOutsidePointer('ds-ppt-filter-overlay', closeDashboardPptFilters);
  closeOnOutsidePointer('ds-editor-overlay', closeTemplateEditor);
  closeOnOutsidePointer('ds-data-overlay', () => overlay('ds-data-overlay', false));
  closeOnOutsidePointer('ds-presentation-overlay', () => overlay('ds-presentation-overlay', false));
  bind('ds-viewer-close', async () => {
    stopPresentation();
    slidePreloadRequest += 1;
    expandedChartPreloadRequest += 1;
    if (!$('ds-chart-expanded-overlay').hidden) expandedChartOverlay(false);
    if (!$('ds-filter-overlay').hidden && !await closeFilters()) return;
    overlay('ds-viewer', false);
  });
  const dashboardDataRequest = async (request) => {
    const parameters = new URLSearchParams({page: String(request.page || 0)});
    const encodedFilters = JSON.stringify(request.column_filters || {});
    if (encodedFilters !== '{}') parameters.set('column_filters', encodedFilters);
    if (request.filter_column) parameters.set('filter_column', request.filter_column);
    const downloadParameters = new URLSearchParams({download: 'true'});
    if (encodedFilters !== '{}') downloadParameters.set('column_filters', encodedFilters);
    $('ds-data-download').href = `/api/e2e-dashboards${dataEndpoint}?${downloadParameters}`;
    return api(`${dataEndpoint}?${parameters}`);
  };
  async function renderData() {
    const token = dataToken;
    const endpoint = dataEndpoint;
    const payload = await dashboardDataRequest({page: 0, column_filters: {}});
    if (token !== dataToken || endpoint !== dataEndpoint) return;
    window.createUnifiedDatasetViewer({
      host: $('ds-data-table'),
      payload,
      requestPage: dashboardDataRequest,
      exportControl: $('ds-data-download'),
    });
  }
  bind('ds-data-close', () => overlay('ds-data-overlay', false));
  bind('ds-chart-expanded-close',()=>expandedChartOverlay(false));
  if ($('ds-edit')) bind('ds-edit',()=>{ const slide = prepared?.slides[slideIndex]; if (slide) openTemplateEditor(slide.focus_row); });
  bind('ds-editor-close', closeTemplateEditor);
  document.addEventListener('keydown',event=>{
    const visible = ['ds-ppt-filter-overlay','ds-chart-expanded-overlay','ds-editor-overlay','ds-data-overlay','ds-filter-overlay','ds-presentation-overlay','ds-viewer'].find(id=>!$(id).hidden && $(id).contains(document.activeElement)); if (!visible) return;
    const editing = event.target.closest?.('input,textarea,select,[contenteditable="true"]');
    if (visible === 'ds-chart-expanded-overlay' && !editing && event.key === 'ArrowLeft') {
      event.preventDefault();
      void safe(() => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) - 1))();
      return;
    }
    if (visible === 'ds-chart-expanded-overlay' && !editing && event.key === 'ArrowRight') {
      event.preventDefault();
      void safe(() => navigateExpandedChart(expandedCharts().findIndex(chart => chart.index === expandedChart?.index) + 1))();
      return;
    }
    if (visible === 'ds-viewer' && !editing && event.key === 'F8') {
      event.preventDefault();
      if (!presentation.active) startPresentation();
      else if (presentation.running) pausePresentation();
      else resumePresentation();
      return;
    }
    if (visible === 'ds-viewer' && !editing && presentation.active && event.key === 'F7') {
      event.preventDefault();
      navigatePresentationSlide(-1);
      return;
    }
    if (visible === 'ds-viewer' && !editing && presentation.active && event.key === 'F9') {
      event.preventDefault();
      navigatePresentationSlide(1);
      return;
    }
    if (visible === 'ds-viewer' && !editing && event.key === 'ArrowLeft' && slideIndex > 0) { event.preventDefault(); if (presentation.active) navigatePresentationSlide(-1); else { slideIndex -= 1; renderSlide(); } return; }
    if (visible === 'ds-viewer' && !editing && event.key === 'ArrowRight' && slideIndex < (prepared?.slides.length || 1) - 1) { event.preventDefault(); if (presentation.active) navigatePresentationSlide(1); else { slideIndex += 1; renderSlide(); } return; }
    if (visible === 'ds-viewer' && !editing && presentation.active && (event.code === 'Space' || event.key === ' ')) {
      event.preventDefault();
      if (presentation.running) pausePresentation(); else resumePresentation();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      if (visible === 'ds-viewer' && presentation.active) { stopPresentation(); return; }
      $({'ds-chart-expanded-overlay':'ds-chart-expanded-close','ds-editor-overlay':'ds-editor-close','ds-data-overlay':'ds-data-close','ds-filter-overlay':'ds-filter-close','ds-ppt-filter-overlay':'ds-ppt-filter-dialog-close','ds-presentation-overlay':'ds-presentation-close','ds-viewer':'ds-viewer-close'}[visible]).click();
    }
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
        let resolvedDashboardChanges = false;
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
          resolvedDashboardChanges = true;
        }
        if (hasUnsavedUniverseChanges()) {
          const choice = await window.showConfirmDialog(
            'This Dashboard has Dataset Universe changes that have not been saved. Save them before leaving?',
            {
              title: 'Unsaved Dataset Universe',
              confirmLabel: 'Save Universe',
              secondaryLabel: 'Discard',
              cancelLabel: 'Cancel',
            },
          );
          if (choice === 'confirm') await savePart('universe');
          else if (choice !== 'secondary') return;
          resolvedDashboardChanges = true;
        }
        if (!resolvedDashboardChanges && !await window.showConfirmDialog(
          'This Dashboard has unsaved changes. Discard them before leaving?',
          {title: 'Unsaved Dashboard changes', confirmLabel: 'Discard', cancelLabel: 'Cancel'},
        )) return;
        dirty = false;
        if (link.classList.contains('topnav-link-logout')) {
          for (const key of [openStorageKey, scrollStorageKey, preparedStorageKey, universeStorageKey]) {
            sessionStorage.removeItem(key);
          }
        }
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
    const restoreOpenDashboard = restorePageState;
    let last = '';
    try {
      last = restoreOpenDashboard ? sessionStorage.getItem(openStorageKey) || '' : '';
      if (!restoreOpenDashboard) sessionStorage.removeItem(openStorageKey);
      const cached = JSON.parse(sessionStorage.getItem(libraryStorageKey) || '{}');
      dashboards = cached && typeof cached === 'object' && !Array.isArray(cached)
        && Object.values(cached).every(item => item && typeof item === 'object' && typeof item.name === 'string') ? cached : {};
      if (Object.keys(dashboards).length) library();
    } catch (_) { dashboards = {}; }
    dashboards = await api(); library();
    if (restorePageState) restoreScroll(); else resetScroll();
    void refreshDashboardStatuses();
    void refreshDashboardPptJobs();
    if (dashboards[last]) await openDashboard(last);
    if (restorePageState) restoreScroll(); else resetScroll();
  })();
  window.setInterval(refreshDashboardStatuses, 2000);
  window.setInterval(refreshDashboardPptJobs, 2000);
  window.addEventListener('dashboard-analytic:refresh-background-tasks', () => { void refreshDashboardStatuses(); void refreshDashboardPptJobs(); });
  window.addEventListener('focus', () => { void refreshDashboardStatuses(); void refreshDashboardPptJobs(); });
})();
