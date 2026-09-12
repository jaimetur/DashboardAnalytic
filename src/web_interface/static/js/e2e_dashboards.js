/* One filter DOM and one definition are shared between the page and the overlay. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('ds-config').textContent);
  let dashboards = {}, activeId = '', definition = null, prepared = null, slideIndex = 0;
  let sequence = 0, timer, controller, preparing = null, dirty = false, dataIndex = 0, dataPage = 0, dataToken = '';
  let presentationTimer = 0;
  const presentation = {running: false, delay: 5000, effect: 'fade'};
  let facetOptions = {}, availableFields = [], facetFields = config.filter_fields || [], facetsLoading = false, facetsRefreshTimer = 0;
  const completedFieldJobs = new Set();
  const chartPayloads = new Map();
  const openStorageKey = `dashboard-analytic:e2e-dashboards:${config.workspace}:open`;
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
  const nextName = value => { let name = value, number = 2; while (Object.values(dashboards).some(item => item.name.toLowerCase() === name.toLowerCase())) name = `${value.slice(0, 108)} (${number++})`; return name; };
  const focusReturn = new Map();
  const status = message => { $('ds-status').textContent = message; };
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
  const option = (value, label) => { const el = node('option', label); el.value = value; return el; };
  const identity = value => String(value).toLocaleLowerCase().replace(/[^a-z0-9]/g, '');
  const api = async (path = '', method = 'GET', body, signal) => {
    const response = await fetch(`/api/e2e-dashboards${path}`, {method, signal, headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail));
    return payload;
  };
  const safe = fn => async (...args) => { try { await fn(...args); } catch (error) { if (error.name !== 'AbortError') { status(error.message); if (window.showInfoDialog) window.showInfoDialog(error.message, {title:'E2E Dashboards',tone:'error'}); } } };
  const bind = (id, fn) => $(id).addEventListener('click', safe(fn));
  const setViewEnabled = enabled => { $('ds-view').disabled = !enabled; };
  const setPreparationState = state => {
    const notice = $('ds-preparing'), viewerNotice = $('ds-viewer-preparing');
    notice.hidden = state === 'hidden';
    viewerNotice.hidden = state !== 'preparing' || $('ds-viewer').hidden;
    if (state === 'hidden') return;
    const ready = state === 'ready';
    notice.dataset.state = state;
    $('ds-preparing-title').textContent = ready ? 'Dashboard is ready' : 'Dashboard is being prepared';
    $('ds-preparing-detail').textContent = ready
      ? 'Data and filters are ready. You can now open View Dashboard.'
      : 'Data and filters are still loading. View Dashboard will become available when preparation is complete.';
  };
  function overlay(id, show) {
    const el = $(id);
    if (show) { focusReturn.set(id, document.activeElement); el.hidden = false; el.querySelector('[role=dialog]').focus(); }
    else { el.hidden = true; focusReturn.get(id)?.focus(); }
    if (id === 'ds-viewer') $('ds-viewer-preparing').hidden = !show || $('ds-preparing').dataset.state !== 'preparing';
    document.body.style.overflow = [...document.querySelectorAll('.ds-overlay')].some(el => !el.hidden) ? 'hidden' : '';
  }
  function library() {
    $('ds-create').disabled = !$('ds-template').options.length;
    $('ds-count').textContent = `Total Dashboards: ${Object.keys(dashboards).length}`;
    const body = $('ds-dashboards-body'); body.replaceChildren();
    const rows = Object.entries(dashboards).sort(([, left], [, right]) => left.name.localeCompare(right.name));
    if (!rows.length) { const row = node('tr'), cell = node('td', 'No Dashboards have been created yet.', 'form-note'); cell.colSpan = 4; row.append(cell); body.append(row); return; }
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
          if (!$('ds-viewer').hidden) renderSlide();
        }
        library(); status(`Renamed Dashboard to “${result.name}”.`);
      });
      nameEditor.append(nameInput, nameSave); nameCell.append(nameEditor);
      row.append(nameCell, node('td', (item.technology || item.template_technology || 'nsa').toUpperCase()), node('td', item.template));
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
  function selectControl(label, values, selected, change, multiple = false) {
    const host = node('label', label), select = document.createElement('select');
    select.multiple = multiple; if (multiple) { select.size = Math.max(2, Math.min(4, values.length)); select.dataset.multiselectAutoClose = '1000'; }
    if (!values.length) { select.disabled = true; select.multiple = false; select.size = 1; select.append(option('', 'No datasets available')); }
    for (const [value, text] of values) { const opt = option(value, text); opt.selected = multiple ? selected.map(String).includes(String(value)) : value === selected; select.append(opt); }
    select.addEventListener('change', () => { change(multiple ? [...select.selectedOptions].map(opt => opt.value) : select.value); changed(); });
    host.append(select); return host;
  }
  function sources() {
    const host = $('ds-sources'); host.replaceChildren();
    for (const kind of ['data','voice','speech']) host.append(selectControl(`CDR ${kind[0].toUpperCase()+kind.slice(1)}`, config.datasets[kind].map(row => [String(row.id), `${row.file_name} · ${row.row_count} rows`]), definition.datasets[kind] || [], values => { definition.datasets[kind] = values.map(Number); }, true));
    host.append(selectControl('Scope', [['single','Operator Comparison'],['multivendor','Multivendor Comparison']], definition.scope, value => { definition.scope = value; }));
    for (const [key, label] of [['date_from', 'Date from'], ['date_to', 'Date to']]) {
      const wrapper = node('label', label), input = document.createElement('input');
      input.type = 'date'; input.value = definition[key] || '';
      input.onchange = () => { definition[key] = input.value || null; changed(); };
      wrapper.append(input); host.append(wrapper);
    }
    globalThis.setupCustomMultiSelects?.();
  }
  function facets() {
    const defaultHost = $('ds-default-facets'), additionalHost = $('ds-additional-facets'); defaultHost.replaceChildren(); additionalHost.replaceChildren();
    definition.hidden_filters ||= [];
    const hidden = new Set(definition.hidden_filters.map(identity));
    const fields = new Set([...facetFields.filter(field => !hidden.has(identity(field))), ...Object.keys(definition.filters), ...definition.custom_fields]);
    for (const field of fields) {
      const facet = node('div', undefined, 'ds-facet');
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
        delete definition.filters[field]; facets(); changed();
      });
      head.append(remove); facet.append(head);
      const values = document.createElement('select'); values.multiple = true; values.size = 1; values.dataset.multiselectAutoClose = '1000'; values.setAttribute('aria-label', `${label} filter`);
      const available = [...new Set([...(facetOptions[field] || []), ...(selected || [])])];
      for (const value of available) {
        const item = option(value, value || '(Empty)'); item.selected = !selected || selected.includes(value); values.append(item);
      }
      if (!available.length) { values.disabled = true; values.append(option('', facetsLoading ? 'Loading values…' : 'No matching values')); }
      values.onchange = () => { definition.filters[field] = [...values.selectedOptions].filter(item => item.value).map(item => item.value); changed(); };
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
  function changed() {
    dirty = true; prepared = null; ++sequence; controller?.abort(); preparing = null;
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
    facetsLoading = true;
    if (!hasOpenFacetMenu()) facets();
    setViewEnabled(false);
    setPreparationState('preparing');
    $('ds-rows').textContent = '';
    try {
      const payload = await api('/prepare','POST',definition,controller.signal);
      if (current !== sequence) return;
      prepared = payload; facetOptions = payload.options; facetFields = payload.filter_fields || facetFields; availableFields = payload.available_fields || payload.custom_fields || []; facetsLoading = false;
      if (hasOpenFacetMenu()) refreshFacetsAfterMenusClose(); else facets();
      setViewEnabled(Boolean(payload.slides?.length)); setPreparationState('ready');
      const rowLabel = payload.rows_exact === false ? 'source rows' : 'rows';
      $('ds-rows').textContent = Object.entries(payload.rows).map(([kind,count]) => `${kind.toUpperCase()}: ${count.toLocaleString()} ${rowLabel}`).join(' · ');
      chartPayloads.clear(); const firstSlideReady = prefetchSlide(0); prefetchRemainingCharts(firstSlideReady);
      if (!$('ds-viewer').hidden) renderSlide();
    } catch (error) { if (current === sequence && error.name !== 'AbortError') { facetsLoading = false; facets(); setViewEnabled(false); setPreparationState('hidden'); $('ds-rows').textContent = error.message; if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div',error.message,'ds-empty')); } throw error; }
    })();
    preparing = pending;
    try { return await pending; }
    finally { if (preparing === pending) preparing = null; }
  }
  async function openDashboard(id) {
    clearTimeout(facetsRefreshTimer);
    stopPresentation();
    activeId = id; definition = structuredClone(dashboards[id]); dirty = false; prepared = null; facetOptions = {}; availableFields = []; slideIndex = 0; setViewEnabled(false); rememberOpen(id);
    $('ds-name').value = definition.name; setNrMode(definition.technology || definition.template_technology, definition.template);
    $('ds-filter-panel').hidden = false; $('ds-dashboard-name').textContent = `Dashboard Name: ${definition.name}`; sources(); facets(); library(); status(''); await prepare();
  }
  async function save() {
    if (!activeId || !definition) return;
    const dashboardId = activeId, item = definition;
    item.name = $('ds-name').value.trim(); await api(`/${dashboardId}`,'PUT',item);
    if (dashboardId !== activeId || item !== definition) return;
    dashboards[dashboardId] = structuredClone(item); dirty = false; library(); status(`Saved “${item.name}”.`);
  }
  const confirmDiscard = async () => !dirty || await window.showConfirmDialog('Discard unsaved Dashboard changes?', {title:'Unsaved changes',confirmLabel:'Discard'});
  bind('ds-create', async () => {
    if (!await confirmDiscard()) return;
    const technology = $('ds-nr-mode').value;
    const selected = (config.templates[technology] || []).find(row => row.identifier === $('ds-template').value);
    if (!selected) throw new Error('Choose a template for the selected NR Mode.');
    const item = {name:$('ds-name').value.trim(),template_technology:technology,template:selected.name,technology,scope:'single',datasets:Object.fromEntries(Object.entries(config.datasets).map(([kind,rows])=>[kind,rows.map(row=>row.id)])),filters:{},custom_fields:[],date_from:null,date_to:null};
    const id = dashboardId(); await api(`/${id}`,'PUT',item); dashboards[id] = item; await openDashboard(id);
  });
  bind('ds-save', save);
  async function duplicateDashboard(sourceId) {
    const id = dashboardId(), item = structuredClone(dashboards[sourceId]); item.name = nextName(`${item.name.slice(0,110)} (copy)`);
    await api(`/${id}`,'PUT',item); dashboards[id] = item; await openDashboard(id);
  }
  function exportDashboard(item) { const blob = new Blob([JSON.stringify({format:'dashboard-analytic-dashboard',version:2,definition:item},null,2)],{type:'application/json'}); const url = URL.createObjectURL(blob), a = node('a'); a.href = url; a.download = `${item.name.replace(/[^a-z0-9_-]/gi,'_')}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); status(`Exported “${item.name}”.`); }
  async function deleteDashboard(id) {
    const item = dashboards[id]; if (!item || !await window.showConfirmDialog(`Delete “${item.name}”?`,{title:'Delete Dashboard',confirmLabel:'Delete',tone:'danger'})) return;
    if (id === activeId && !await confirmDiscard()) return;
    await api(`/${id}`,'DELETE'); delete dashboards[id]; if (id === activeId) closeDashboard(); else library();
  }
  bind('ds-import',() => $('ds-import-file').click());
  $('ds-import-file').onchange = safe(async () => { const file = $('ds-import-file').files[0]; if (!file) return; const payload = JSON.parse(await file.text()); const legacy = payload.format === 'dashboard-analytic-dashboard-set' && payload.version === 1; if (!legacy && (payload.format !== 'dashboard-analytic-dashboard' || payload.version !== 2)) throw new Error('Unsupported Dashboard file.'); if (!await confirmDiscard()) return; payload.definition.name = nextName(payload.definition.name); const id = dashboardId(); await api(`/${id}`,'PUT',payload.definition); dashboards[id] = payload.definition; await openDashboard(id); $('ds-import-file').value = ''; });
  function closeDashboard() { clearTimeout(facetsRefreshTimer); stopPresentation(); rememberOpen(''); ++sequence; clearTimeout(timer); controller?.abort(); preparing = null; activeId = ''; definition = null; prepared = null; dirty = false; setViewEnabled(false); setPreparationState('hidden'); $('ds-filter-panel').hidden = true; $('ds-dashboard-name').textContent = 'Dashboard Name: —'; $('ds-name').value = ''; setNrMode('nsa'); library(); status('Dashboard closed.'); }
  $('ds-name').oninput = () => { if (definition) { definition.name = $('ds-name').value; dirty = true; } };
  $('ds-nr-mode').onchange = () => {
    const selected = setNrMode($('ds-nr-mode').value);
    if (definition && selected) { definition.template_technology = definition.technology = $('ds-nr-mode').value; definition.template = selected.name; changed(); }
  };
  $('ds-template').onchange = () => { if (definition) { setTemplate($('ds-template').value); changed(); } };
  bind('ds-add-filter',() => { const field = $('ds-custom-field').value; if (!field) return; const defaultField = facetFields.find(item => identity(item) === identity(field)); if (defaultField) definition.hidden_filters = definition.hidden_filters.filter(item => identity(item) !== identity(defaultField)); else definition.custom_fields.push(field); facets(); changed(); });
  bind('ds-reset',() => { definition.filters = {}; definition.date_from = definition.date_to = null; changed(); });
  bind('ds-refresh',prepare); bind('ds-viewer-refresh',prepare);
  bind('ds-view',async () => { if (!prepared?.slides.length) return; overlay('ds-viewer',true); renderSlide(); });
  function loadChartPayload(chart) {
    const url = `/api/e2e-dashboards/chart/${prepared.token}/${chart.index}`;
    let request = chartPayloads.get(url);
    if (!request) {
      request = fetch(url).then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Unable to prepare chart data.');
        return payload;
      });
      chartPayloads.set(url, request);
      while (chartPayloads.size > 160) chartPayloads.delete(chartPayloads.keys().next().value);
    }
    return request;
  }
  function prefetchSlide(index) {
    const slide = prepared?.slides[index]; if (!slide) return Promise.resolve([]);
    const requests = [];
    for (const chart of slide.charts) {
      if (!chart.available) continue;
      requests.push(loadChartPayload(chart));
    }
    return Promise.allSettled(requests);
  }
  function prefetchRemainingCharts(firstSlideReady = Promise.resolve()) {
    const token = prepared?.token;
    if (!token) return;
    let index = 1;
    const next = async () => {
      if (prepared?.token !== token || index >= prepared.slides.length) return;
      await prefetchSlide(index++);
      setTimeout(next, 60);
    };
    firstSlideReady.finally(() => setTimeout(next, 60));
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
    sync(1); controls.append(zoomOut, level, zoomIn, reset); return controls;
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
  function renderSlide() {
    if (!prepared) return; slideIndex = Math.max(0,Math.min(slideIndex,prepared.slides.length-1));
    const slide = prepared.slides[slideIndex]; if (!slide) return;
    $('ds-title').textContent = slide.title || `Dashboard ${slide.number}`; $('ds-subtitle').textContent = slide.subtitle;
    $('ds-position').textContent = `${definition.name} · Dashboard ${slideIndex+1} / ${prepared.slides.length}`;
    $('ds-slide').replaceChildren(...prepared.slides.map((item,index)=>option(String(index),`${item.number} · ${item.title || 'Dashboard'}`))); $('ds-slide').value = String(slideIndex);
    $('ds-first').disabled = $('ds-prev').disabled = slideIndex === 0;
    $('ds-next').disabled = $('ds-last').disabled = slideIndex === prepared.slides.length - 1;
    $('ds-slide-content').classList.toggle('ds-comments-right', /\bcomments\s+right\b/i.test(slide.layout || ''));
    const stage = $('ds-charts'); stage.classList.remove('ds-slide-transition'); stage.replaceChildren(); stage.classList.toggle('ds-positioned',slide.charts.length > 0 && slide.charts.every(chart=>chart.position)); stage.classList.toggle('ds-structural-stage', !slide.charts.length);
    if (!slide.charts.length) structuralDashboard(stage, slide);
    for (const chart of slide.charts) {
      const card = node('article',undefined,'ds-chart'); card.setAttribute('aria-label',chart.title); card.tabIndex = 0;
      if (chart.position) { const [left,top,width,height] = chart.position; Object.assign(card.style,{left:`${left}%`,top:`${top}%`,width:`${width}%`,height:`${height}%`}); }
      const message = node('div',`Rendering ${chart.title || 'chart'}…`,'ds-chart-message'); card.append(message);
      const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', chart.title); canvas.hidden = true; card.append(canvas);
      const zoom = chartZoomControls(canvas); card.append(zoom);
      if (chart.available) {
        const token = prepared.token;
        loadChartPayload(chart).then(payload => {
          if (!card.isConnected || prepared?.token !== token) return;
          canvas.hidden = false;
          requestAnimationFrame(() => {
            try { globalThis.renderDashboardChart(canvas, payload); zoom.hidden = false; message.remove(); }
            catch (error) { canvas.hidden = true; message.textContent = error.message || `Unable to render ${chart.title || 'chart'}.`; }
          });
        }).catch(error => {
          if (prepared?.token === token) message.textContent = error.message || `Unable to render ${chart.title || 'chart'}.`;
        });
      } else message.textContent = `Unavailable source type: select a ${chart.source ? chart.source.toUpperCase() : 'supported'} CDR dataset.`;
      const data = node('button','', 'ds-chart-data'); data.type = 'button'; data.title = 'View dataset'; data.setAttribute('aria-label', 'View dataset'); data.disabled = !chart.available; data.onclick = safe(async () => { dataIndex = chart.index; dataPage = 0; dataToken = prepared.token; overlay('ds-data-overlay',true); await renderData(); });
      const controls = node('div', undefined, 'ds-chart-controls'); controls.append(data, zoom); card.append(controls);
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
    renderComments(); prefetchSlide(slideIndex + 1);
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
  const closeFilters = () => { $('ds-filter-home').append($('ds-filter-panel')); $('ds-view').hidden = false; $('ds-filter-close-action').hidden = true; overlay('ds-filter-overlay',false); };
  bind('ds-floating-filters',()=>{ $('ds-filter-float').append($('ds-filter-panel')); $('ds-view').hidden = true; $('ds-filter-close-action').hidden = false; overlay('ds-filter-overlay',true); });
  bind('ds-filter-close',closeFilters);
  bind('ds-filter-close-action',closeFilters);
  bind('ds-viewer-close',()=>{ stopPresentation(); if (!$('ds-filter-overlay').hidden) closeFilters(); overlay('ds-viewer',false); });
  async function renderData() {
    $('ds-data-table').textContent = 'Loading chart dataset…';
    const token = dataToken, payload = await api(`/data/${token}/${dataIndex}?page=${dataPage}`);
    const table = node('table'), head = node('thead'), header = node('tr'); payload.columns.forEach(column=>header.append(node('th',column))); head.append(header); table.append(head);
    const body = node('tbody'); for (const row of payload.rows) { const tr = node('tr'); row.forEach(value=>tr.append(node('td',value))); body.append(tr); } table.append(body); $('ds-data-table').replaceChildren(table);
    $('ds-data-page').textContent = `${payload.total.toLocaleString()} rows · Page ${dataPage+1} / ${Math.max(1,Math.ceil(payload.total/100))}`;
    $('ds-data-prev').disabled = dataPage === 0; $('ds-data-next').disabled = (dataPage+1)*100 >= payload.total;
    $('ds-data-download').href = `/api/e2e-dashboards/data/${token}/${dataIndex}?download=true`;
  }
  bind('ds-data-prev',async ()=>{ dataPage--; await renderData(); }); bind('ds-data-next',async ()=>{ dataPage++; await renderData(); }); bind('ds-data-close',()=>overlay('ds-data-overlay',false));
  if ($('ds-edit')) bind('ds-edit',()=>{ const slide = prepared?.slides[slideIndex]; if (!slide) return; $('ds-editor-frame').src = `/admin/report-templates/${encodeURIComponent(definition.template_technology)}/${encodeURIComponent(definition.template)}/editor?focus_row=${slide.focus_row}`; overlay('ds-editor-overlay',true); });
  bind('ds-editor-close',async ()=>{ overlay('ds-editor-overlay',false); $('ds-editor-frame').removeAttribute('src'); await prepare(); });
  document.addEventListener('keydown',event=>{
    const visible = ['ds-editor-overlay','ds-data-overlay','ds-filter-overlay','ds-presentation-overlay','ds-viewer'].find(id=>!$(id).hidden); if (!visible || !$(visible).contains(document.activeElement)) return;
    if (event.key === 'Escape') { event.preventDefault(); $({'ds-editor-overlay':'ds-editor-close','ds-data-overlay':'ds-data-close','ds-filter-overlay':'ds-filter-close','ds-presentation-overlay':'ds-presentation-close','ds-viewer':'ds-viewer-close'}[visible]).click(); }
    if (event.key === 'Tab') { const controls = [...$(visible).querySelectorAll('button:not(:disabled),a[href],input,select,summary,[tabindex="0"]')].filter(el=>el.getClientRects().length); if (!controls.length) return; const first = controls[0], last = controls.at(-1); if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
  });
  window.addEventListener('message', event => {
    if (event.origin === window.location.origin && event.source === $('ds-editor-frame').contentWindow && event.data?.type === 'dashboard-analytic:close-template-editor') $('ds-editor-close').click();
  });
  window.addEventListener('beforeunload',event=>{ if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('auto-calculated-field-job-status',event=>{ const job = event.detail; if (definition && job?.id && ['ready','completed'].includes(job.status) && !completedFieldJobs.has(job.id)) { completedFieldJobs.add(job.id); changed(); } });
  safe(async ()=>{ dashboards = await api(); library(); let last = ''; try { last = sessionStorage.getItem(openStorageKey) || ''; } catch (_) { /* Storage is optional. */ } if (dashboards[last]) await openDashboard(last); })();
})();
