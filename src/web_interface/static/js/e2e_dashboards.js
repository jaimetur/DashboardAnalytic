/* One filter DOM and one definition are shared between the page and the overlay. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('ds-config').textContent);
  let dashboards = {}, activeId = '', definition = null, prepared = null, slideIndex = 0;
  let sequence = 0, timer, controller, preparing = null, dirty = false, dataIndex = 0, dataPage = 0, dataToken = '';
  let facetOptions = {}, availableFields = [], facetFields = config.filter_fields || [], facetsLoading = false;
  const completedFieldJobs = new Set();
  const prefetchedChartUrls = new Set();
  const prefetchedCharts = new Map();
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
  function overlay(id, show) {
    const el = $(id);
    if (show) { focusReturn.set(id, document.activeElement); el.hidden = false; el.querySelector('[role=dialog]').focus(); }
    else { el.hidden = true; focusReturn.get(id)?.focus(); }
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
      row.append(node('td', item.name), node('td', (item.technology || item.template_technology || 'nsa').toUpperCase()), node('td', item.template));
      const actions = node('div', undefined, 'ds-dashboard-actions');
      const action = (label, glyph, handler, tone = '') => {
        const button = node('button', glyph, `icon-action ds-dashboard-action ${tone}`); button.type = 'button'; button.title = label; button.setAttribute('aria-label', label); button.onclick = safe(handler); actions.append(button);
      };
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
    select.multiple = multiple; if (multiple) select.size = Math.max(2, Math.min(4, values.length));
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
    const host = $('ds-facets'); host.replaceChildren();
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
      const values = document.createElement('select'); values.multiple = true; values.size = 1; values.setAttribute('aria-label', `${label} filter`);
      const available = [...new Set([...(facetOptions[field] || []), ...(selected || [])])];
      for (const value of available) {
        const item = option(value, value || '(Empty)'); item.selected = !selected || selected.includes(value); values.append(item);
      }
      if (!available.length) { values.disabled = true; values.append(option('', facetsLoading ? 'Loading values…' : 'No matching values')); }
      values.onchange = () => { definition.filters[field] = [...values.selectedOptions].filter(item => item.value).map(item => item.value); changed(); };
      facet.append(values);
      host.append(facet);
    }
    const visible = [...fields].map(field => identity(field));
    const restorable = facetFields.filter(field => hidden.has(identity(field)));
    const choices = [...restorable, ...availableFields].filter((field, index, all) => !visible.includes(identity(field)) && all.findIndex(item => identity(item) === identity(field)) === index);
    $('ds-custom-field').replaceChildren(...choices.map(field => option(field, field)));
    $('ds-add-filter').disabled = !$('ds-custom-field').options.length;
    globalThis.setupCustomMultiSelects?.();
  }
  function changed() {
    dirty = true; prepared = null; ++sequence; controller?.abort(); preparing = null;
    setViewEnabled(false);
    $('ds-rows').textContent = 'Updating all dashboards…';
    if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div','Updating dashboards…','ds-empty'));
    clearTimeout(timer); timer = setTimeout(safe(prepare), 350);
  }
  async function prepare() {
    if (preparing) return preparing;
    const pending = (async () => {
    clearTimeout(timer); const current = ++sequence; controller?.abort(); controller = new AbortController();
    facetsLoading = true; facets();
    setViewEnabled(false);
    $('ds-rows').textContent = 'Preparing shared CDR data… View Dashboard will open when it is ready.';
    try {
      const payload = await api('/prepare','POST',definition,controller.signal);
      if (current !== sequence) return;
      prepared = payload; facetOptions = payload.options; facetFields = payload.filter_fields || facetFields; availableFields = payload.available_fields || payload.custom_fields || []; facetsLoading = false; facets(); setViewEnabled(Boolean(payload.slides?.length));
      $('ds-rows').textContent = Object.entries(payload.rows).map(([kind,count]) => `${kind.toUpperCase()}: ${count.toLocaleString()} rows`).join(' · ');
      if (!$('ds-viewer').hidden) renderSlide();
    } catch (error) { if (current === sequence && error.name !== 'AbortError') { facetsLoading = false; facets(); setViewEnabled(false); $('ds-rows').textContent = error.message; if (!$('ds-viewer').hidden) $('ds-charts').replaceChildren(node('div',error.message,'ds-empty')); } throw error; }
    })();
    preparing = pending;
    try { return await pending; }
    finally { if (preparing === pending) preparing = null; }
  }
  async function openDashboard(id) {
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
  function closeDashboard() { rememberOpen(''); ++sequence; clearTimeout(timer); controller?.abort(); preparing = null; activeId = ''; definition = null; prepared = null; dirty = false; setViewEnabled(false); $('ds-filter-panel').hidden = true; $('ds-dashboard-name').textContent = 'Dashboard Name: —'; $('ds-name').value = ''; setNrMode('nsa'); library(); status('Dashboard closed.'); }
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
  function prefetchSlide(index) {
    const slide = prepared?.slides[index]; if (!slide) return;
    for (const chart of slide.charts) {
      if (!chart.available) continue;
      const url = `/api/e2e-dashboards/preview/${prepared.token}/${chart.index}.png`;
      if (prefetchedChartUrls.has(url)) continue;
      prefetchedChartUrls.add(url); const image = new Image(); image.src = url; prefetchedCharts.set(url, image);
      while (prefetchedCharts.size > 24) prefetchedCharts.delete(prefetchedCharts.keys().next().value);
    }
  }
  function renderSlide() {
    if (!prepared) return; slideIndex = Math.max(0,Math.min(slideIndex,prepared.slides.length-1));
    const slide = prepared.slides[slideIndex]; if (!slide) return;
    $('ds-title').textContent = slide.title || `Dashboard ${slide.number}`; $('ds-subtitle').textContent = slide.subtitle;
    $('ds-position').textContent = `${definition.name} · Dashboard ${slideIndex+1} / ${prepared.slides.length}`;
    $('ds-slide').replaceChildren(...prepared.slides.map((item,index)=>option(String(index),`${item.number} · ${item.title || 'Dashboard'}`))); $('ds-slide').value = String(slideIndex);
    $('ds-prev').disabled = slideIndex === 0; $('ds-next').disabled = slideIndex === prepared.slides.length-1;
    const stage = $('ds-charts'); stage.replaceChildren(); stage.classList.toggle('ds-positioned',slide.charts.length > 0 && slide.charts.every(chart=>chart.position));
    if (!slide.charts.length) stage.append(node('div',slide.title || 'Section dashboard','ds-empty'));
    for (const chart of slide.charts) {
      const card = node('article',undefined,'ds-chart'); card.setAttribute('aria-label',chart.title); card.tabIndex = 0;
      if (chart.position) { const [left,top,width,height] = chart.position; Object.assign(card.style,{left:`${left}%`,top:`${top}%`,width:`${width}%`,height:`${height}%`}); }
      const message = node('div',`Rendering ${chart.title || 'chart'}…`,'ds-chart-message'); card.append(message);
      const image = document.createElement('img'); image.alt = chart.title; image.hidden = true; if (chart.available) image.src = `/api/e2e-dashboards/preview/${prepared.token}/${chart.index}.png`; else message.textContent = `Unavailable source type: select a ${chart.source ? chart.source.toUpperCase() : 'supported'} CDR dataset.`;
      image.onload = () => { message.remove(); image.hidden = false; }; image.onerror = () => { message.textContent = `Unable to render ${chart.title || 'chart'}. Check the selected source, template fields and filters, then refresh.`; };
      card.append(image);
      const data = node('button','View Dataset','ds-chart-data'); data.type = 'button'; data.disabled = !chart.available; data.onclick = safe(async () => { dataIndex = chart.index; dataPage = 0; dataToken = prepared.token; overlay('ds-data-overlay',true); await renderData(); }); card.append(data);
      let hideTimer;
      const hideDataAction = () => { if (!hideTimer) hideTimer = setTimeout(() => { card.classList.remove('ds-hover'); hideTimer = null; }, 2000); };
      card.onpointermove = event => { const bounds = card.getBoundingClientRect(); if (event.clientX > bounds.right - 160 && event.clientY < bounds.top + 65) { clearTimeout(hideTimer); hideTimer = null; card.classList.add('ds-hover'); } else hideDataAction(); };
      card.onpointerleave = hideDataAction;
      stage.append(card);
    }
    prefetchSlide(slideIndex + 1);
  }
  bind('ds-prev',()=>{ slideIndex--; renderSlide(); }); bind('ds-next',()=>{ slideIndex++; renderSlide(); });
  $('ds-slide').onchange = () => { slideIndex = Number($('ds-slide').value); renderSlide(); };
  const closeFilters = () => { $('ds-filter-home').append($('ds-filter-panel')); overlay('ds-filter-overlay',false); };
  bind('ds-floating-filters',()=>{ $('ds-filter-float').append($('ds-filter-panel')); overlay('ds-filter-overlay',true); });
  bind('ds-filter-close',closeFilters);
  bind('ds-viewer-close',()=>{ if (!$('ds-filter-overlay').hidden) closeFilters(); overlay('ds-viewer',false); });
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
    const visible = ['ds-editor-overlay','ds-data-overlay','ds-filter-overlay','ds-viewer'].find(id=>!$(id).hidden); if (!visible || !$(visible).contains(document.activeElement)) return;
    if (event.key === 'Escape') { event.preventDefault(); $({'ds-editor-overlay':'ds-editor-close','ds-data-overlay':'ds-data-close','ds-filter-overlay':'ds-filter-close','ds-viewer':'ds-viewer-close'}[visible]).click(); }
    if (event.key === 'Tab') { const controls = [...$(visible).querySelectorAll('button:not(:disabled),a[href],input,select,summary,[tabindex="0"]')].filter(el=>el.getClientRects().length); if (!controls.length) return; const first = controls[0], last = controls.at(-1); if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
  });
  window.addEventListener('message', event => {
    if (event.origin === window.location.origin && event.source === $('ds-editor-frame').contentWindow && event.data?.type === 'dashboard-analytic:close-template-editor') $('ds-editor-close').click();
  });
  window.addEventListener('beforeunload',event=>{ if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('auto-calculated-field-job-status',event=>{ const job = event.detail; if (definition && job?.id && ['ready','completed'].includes(job.status) && !completedFieldJobs.has(job.id)) { completedFieldJobs.add(job.id); changed(); } });
  safe(async ()=>{ dashboards = await api(); library(); let last = ''; try { last = sessionStorage.getItem(openStorageKey) || ''; } catch (_) { /* Storage is optional. */ } if (dashboards[last]) await openDashboard(last); })();
})();
