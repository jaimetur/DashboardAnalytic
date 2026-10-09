/* Network Insights: one shared selection drives every panel. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('ni-config').textContent);
  $('ni-cities').dataset.multiselectPresetValues = (config.main_cities || []).join('|');
  $('ni-cities').dispatchEvent(new Event('multiselect:options-updated'));
  const storageKey = config.selection_storage_key;
  let savedSelection = {};
  try {
    const stored = storageKey ? JSON.parse(localStorage.getItem(storageKey) || '{}') : {};
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) savedSelection = stored;
  } catch {}
  const selectionControls = ['ni-nr-mode', 'ni-technology', 'ni-group', 'ni-coverage-threshold',
    'ni-interference-threshold', 'ni-nr-coverage-threshold', 'ni-nr-interference-threshold', 'ni-grid',
    'ni-deployment-group', 'ni-sites-source'];
  for (const id of selectionControls) {
    const control = $(id);
    const value = savedSelection.controls?.[id];
    if (value === undefined) continue;
    if (control.multiple && Array.isArray(value)) {
      for (const option of control.options) option.selected = value.includes(option.value);
      control.dispatchEvent(new Event('multiselect:options-updated'));
    } else if (control.tagName === 'SELECT') {
      if ([...control.options].some(option => option.value === String(value) && !option.disabled)) control.value = value;
    } else if (Number.isFinite(Number(value))) control.value = value;
  }
  const pendingFilterRestore = new Map(Object.entries(savedSelection.filters || {})
    .filter(([, values]) => Array.isArray(values)));
  let restoreDatasets = true;
  const syncTechnologyGrouping = () => {
    const control = $('ni-group');
    // LTE+NR analyses LTE and NR in separate sections, each with its own
    // thresholds, so Technology is never a grouping and RSRP/SINR are never pooled.
    const existing = [...control.options].find(option => option.value === 'technology');
    if (existing) {
      existing.remove();
      control.dispatchEvent(new Event('multiselect:options-updated'));
    }
    const technology = $('ni-technology').value;
    document.querySelectorAll('[data-ni-radio]').forEach(label => {
      label.hidden = ![label.dataset.niRadio, 'lte_nr'].includes(technology);
    });
  };
  syncTechnologyGrouping();
  // Operator stays checked unless Vendor is checked.
  const enforceOperatorGrouping = () => {
    const control = $('ni-group');
    const option = value => [...control.options].find(item => item.value === value);
    const operator = option('operator');
    if (!operator) return;
    const required = !option('vendor')?.selected;
    const changed = operator.disabled !== required || (required && !operator.selected);
    operator.disabled = required;
    operator.dataset.disabledReason = 'Operator is required unless Vendor is selected.';
    if (required) operator.selected = true;
    // Synchronize the existing menu without rebuilding and closing it.
    if (changed) control.dispatchEvent(new Event('change', {bubbles: true}));
  };
  enforceOperatorGrouping();
  $('ni-group').addEventListener('change', enforceOperatorGrouping);
  const kinds = [['data', 'CDR Data'], ['voice', 'CDR Voice'], ['speech', 'CDR Speech']];
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const number = (value, digits = 1) => (value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits));
  const integer = value => (Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US') : '—');
  let analysis = null;
  let analysing = 0;
  // Map payloads by `<technology>-<coverage|interference>`.
  const mapPayloads = {};
  const sections = () => analysis?.sections || (analysis ? [analysis] : []);
  const multipleSections = () => sections().length > 1;

  const status = (message, tone = '') => {
    const element = $('ni-status');
    element.textContent = message;
    element.dataset.tone = tone;
  };

  // Select every available CDR for the NR Mode unless a saved selection overrides it.
  const renderDatasets = () => {
    const nrMode = $('ni-nr-mode').value;
    const host = $('ni-datasets');
    host.replaceChildren();
    for (const [kind, label] of kinds) {
      const rows = (config.datasets || []).filter(row => row.kind === kind && String(row.nr_mode || '').toUpperCase() === nrMode);
      const group = document.createElement('section');
      group.className = 'ni-dataset-group';
      group.innerHTML = `<div class="ni-dataset-head"><h3>${escapeHtml(label)} <span>(${escapeHtml(nrMode)})</span></h3>${rows.length ? `<button type="button" class="ni-dataset-toggle" data-ni-select-kind="${kind}">Select All</button>` : ''}</div>`;
      if (!rows.length) group.insertAdjacentHTML('beforeend', '<p class="form-note">No ready CDRs.</p>');
      const restored = restoreDatasets && Array.isArray(savedSelection.datasets?.[kind]) ? new Set(savedSelection.datasets[kind].map(Number)) : null;
      rows.forEach((row, index) => {
        const option = document.createElement('label');
        option.className = 'ni-dataset-option';
        // Weekly and Daily CDRs are highlighted.
        option.dataset.cdrStage = row.cdr_stage || 'final';
        const stage = ['weekly', 'daily'].includes(row.cdr_stage)
          ? `<span class="cdr-stage-badge" data-cdr-stage="${row.cdr_stage}">${row.cdr_stage === 'weekly' ? 'Weekly' : 'Daily'}</span> ` : '';
        option.innerHTML = `<input type="checkbox" value="${row.id}" data-kind="${kind}"${(restored ? restored.has(Number(row.id)) : true) ? ' checked' : ''}><span>${stage}${escapeHtml(row.file_name)} · ${integer(row.row_count)} rows</span>`;
        group.append(option);
      });
      host.append(group);
    }
    restoreDatasets = false;
    syncDatasetToggles();
  };
  // Each CDR type selects all its CDRs, or clears them when all are selected.
  const syncDatasetToggles = () => {
    document.querySelectorAll('[data-ni-select-kind]').forEach(button => {
      const boxes = [...document.querySelectorAll(`#ni-datasets input[data-kind="${button.dataset.niSelectKind}"]`)];
      button.textContent = boxes.length && boxes.every(box => box.checked) ? 'Select None' : 'Select All';
    });
  };
  $('ni-datasets').addEventListener('click', event => {
    const button = event.target.closest('[data-ni-select-kind]');
    if (!button) return;
    const boxes = [...document.querySelectorAll(`#ni-datasets input[data-kind="${button.dataset.niSelectKind}"]`)];
    const select = !boxes.every(box => box.checked);
    boxes.forEach(box => { box.checked = select; });
    boxes[0]?.dispatchEvent(new Event('change', {bubbles: true}));
  });
  $('ni-datasets').addEventListener('change', syncDatasetToggles);
  const selectedDatasets = () => Object.fromEntries(kinds.map(([kind]) => [kind,
    [...document.querySelectorAll(`#ni-datasets input[data-kind="${kind}"]:checked`)].map(input => Number(input.value))]));
  const selectedValues = id => [...$(id).selectedOptions].map(option => option.value);
  const allSelected = id => {
    const options = [...$(id).options].filter(option => option.value);
    return options.length > 0 && options.every(option => option.selected);
  };
  // An unfiltered selector (every value or none) sends no restriction.
  const filterValues = id => (allSelected(id) ? [] : selectedValues(id));
  // Campaigns as the workspace Campaign Maps show them (campaign_labels.js); the filter keeps the full value.
  const campaignLabel = (value) => (globalThis.campaignLabel ? globalThis.campaignLabel(value) : String(value ?? ''));
  const fillSelector = (id, values) => {
    const control = $(id);
    const restored = pendingFilterRestore.get(id);
    const previous = new Set(restored || selectedValues(id));
    const keepAll = restored ? !restored.length : !control.options.length || allSelected(id) || !previous.size;
    pendingFilterRestore.delete(id);
    control.dataset.multiselectNoValuesLabel = 'No values available';
    control.replaceChildren(...values.map(value => {
      const option = document.createElement('option');
      option.value = value; option.textContent = id === 'ni-campaigns' ? campaignLabel(value) : value;
      option.selected = keepAll || previous.has(value);
      return option;
    }));
    control.dispatchEvent(new Event('multiselect:options-updated'));
  };

  const filterNames = ['operators', 'operator_vendors', 'vendor_operators', 'vendors', 'regions', 'clusters', 'cities', 'campaigns'];
  const fillFilterOptions = options => {
    if (options.operators) $('ni-vendors').dataset.multiselectOperatorValues = JSON.stringify(options.operators);
    for (const field of filterNames) {
      if (Object.prototype.hasOwnProperty.call(options, field)) fillSelector(`ni-${field}`, options[field] || []);
    }
  };
  let optionsRequest = null;
  let optionsTimer = null;
  const optionsCache = new Map();
  const loadFilterOptions = async () => {
    optionsRequest?.abort();
    const datasets = selectedDatasets();
    const key = JSON.stringify(datasets);
    const cached = optionsCache.get(key);
    if (cached) fillFilterOptions(cached);
    if (cached && filterNames.every(field => Object.prototype.hasOwnProperty.call(cached, field))) return;
    const controller = new AbortController();
    optionsRequest = controller;
    for (const field of filterNames) {
      if (cached && Object.prototype.hasOwnProperty.call(cached, field)) continue;
      const control = $(`ni-${field}`);
      control.dataset.multiselectNoValuesLabel = 'Loading values…';
      const trigger = control.nextElementSibling?.querySelector('.multiselect-trigger-label');
      if (trigger) trigger.textContent = 'Loading values…';
    }
    try {
      const loadPart = async vendorOnly => {
        const response = await fetch(`/api/network-insights/filter-options${vendorOnly ? '?vendor_only=true' : ''}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({datasets}), signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Unable to load filter values.');
        if (controller.signal.aborted) return;
        const merged = {...(optionsCache.get(key) || {}), ...payload.options};
        optionsCache.set(key, merged);
        fillFilterOptions(payload.options);
        refreshInventory();
      };
      // Cached dimensions render independently of the first Vendor lookup.
      const results = await Promise.allSettled([loadPart(false), loadPart(true)]);
      const failure = results.find(result => result.status === 'rejected');
      if (failure) throw failure.reason;
    } catch (error) {
      if (error.name !== 'AbortError') {
        for (const field of filterNames) {
          if (Object.prototype.hasOwnProperty.call(optionsCache.get(key) || {}, field)) continue;
          const control = $(`ni-${field}`);
          control.dataset.multiselectNoValuesLabel = 'Unable to load values';
          control.dispatchEvent(new Event('multiselect:options-updated'));
        }
        status(error.message, 'error');
      }
    }
  };
  const scheduleFilterOptions = () => {
    clearTimeout(optionsTimer);
    optionsRequest?.abort();
    optionsTimer = setTimeout(() => { void loadFilterOptions(); }, 150);
  };

  const requestBody = (mapOperator = '') => ({
    datasets: selectedDatasets(),
    nr_mode: $('ni-nr-mode').value,
    technology: $('ni-technology').value,
    group: selectedValues('ni-group'),
    operators: filterValues('ni-operators'),
    operator_vendors: filterValues('ni-operator_vendors'),
    vendor_operators: filterValues('ni-vendor_operators'),
    vendors: filterValues('ni-vendors'),
    campaigns: filterValues('ni-campaigns'),
    regions: filterValues('ni-regions'),
    clusters: filterValues('ni-clusters'),
    cities: filterValues('ni-cities'),
    coverage_threshold: Number($('ni-coverage-threshold').value),
    interference_threshold: Number($('ni-interference-threshold').value),
    nr_coverage_threshold: Number($('ni-nr-coverage-threshold').value),
    nr_interference_threshold: Number($('ni-nr-interference-threshold').value),
    grid_metres: Number($('ni-grid').value),
    min_samples: 3,
    map_operator: mapOperator,
  });

  // Modal shown while an analysis runs; Hide leaves it running in the background.
  const progress = {timer: null, started: 0};
  const showProgress = (message, title = 'Network analysis in progress') => {
    const dialog = $('ni-progress-dialog');
    $('ni-progress-title').textContent = title;
    $('ni-progress-message').textContent = message;
    progress.started = Date.now();
    const tick = () => { $('ni-progress-elapsed').textContent = `Elapsed: ${Math.floor((Date.now() - progress.started) / 1000)} s`; };
    tick();
    clearInterval(progress.timer);
    progress.timer = setInterval(tick, 1000);
    if (!dialog.open) dialog.showModal?.();
  };
  const hideProgress = () => {
    clearInterval(progress.timer);
    const dialog = $('ni-progress-dialog');
    if (dialog.open) dialog.close();
  };
  $('ni-progress-hide').onclick = hideProgress;
  $('ni-progress-dialog').addEventListener('cancel', () => clearInterval(progress.timer));

  // The last analysed request, to show its stored result again when the page
  // opens with the same selection.
  const lastAnalysisKey = storageKey ? `${storageKey}:last-analysis` : '';
  const readLastAnalysis = () => {
    try { return JSON.parse(localStorage.getItem(lastAnalysisKey) || 'null'); } catch { return null; }
  };
  const analyse = async (mapOperator = '', {cachedOnly = false} = {}) => {
    const request = ++analysing;
    const button = $('ni-analyse');
    const body = requestBody(mapOperator);
    button.disabled = true; button.classList.add('is-busy');
    if (cachedOnly) {
      status('Showing the last analysis of this selection…', 'busy');
    } else {
      status('Analysing the selected CDRs… CDRs analysed for the first time are read and prepared first.', 'busy');
      showProgress('Analysing the selected CDRs. CDRs analysed for the first time (or changed since) are read and prepared first, which can take from a few seconds to a minute or more depending on their size; after that, new filters take a few seconds and repeated analyses are immediate.');
    }
    try {
      const response = await fetch(`/api/network-insights/analysis${cachedOnly ? '?cached_only=true' : ''}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      });
      if (cachedOnly && response.status === 204) {
        if (request === analysing) status('');
        return;
      }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to analyse the selected CDRs.');
      if (request !== analysing) return;
      analysis = payload;
      try { if (lastAnalysisKey) localStorage.setItem(lastAnalysisKey, JSON.stringify(body)); } catch {}
      fillFilterOptions(payload.options);
      render();
      const comparison = payload.comparison ? ` Changes compare ${payload.comparison.latest} with ${payload.comparison.previous}.` : '';
      const counts = (payload.sections || [payload]).map(section =>
        `${integer(section.overview.reduce((total, row) => total + row.samples, 0))} ${section.technology_label}`).join(' and ');
      status(`Analysed ${counts} samples.${comparison}${payload.warnings.length ? ` ${payload.warnings.join(' ')}` : ''}`, payload.warnings.length ? 'warning' : 'done');
    } catch (error) {
      if (request === analysing) status(cachedOnly ? '' : error.message, cachedOnly ? '' : 'error');
    } finally {
      if (request === analysing) { button.disabled = false; button.classList.remove('is-busy'); hideProgress(); }
    }
  };
  // Opening or reloading the page with the selection of the last analysis shows
  // its stored result; a changed selection waits for Analyse Network.
  const showLastAnalysis = () => {
    const last = readLastAnalysis();
    if (!last || analysis || analysing) return;
    const comparable = body => JSON.stringify({...body, map_operator: ''});
    if (comparable(requestBody()) === comparable(last)) void analyse(last.map_operator || '', {cachedOnly: true});
  };

  // Summary Network Insights of the current selection, as PowerPoint or Word.
  document.querySelectorAll('[data-ni-export]').forEach((button) => button.addEventListener('click', async () => {
    const kind = button.dataset.niExport;
    const label = kind === 'word' ? 'Word' : 'PowerPoint';
    button.disabled = true; button.classList.add('is-busy');
    status(`Generating the Summary Network Insights ${label}… Charts and maps are rendered at full size.`, 'busy');
    showProgress(`Preparing the Summary Network Insights ${label}: the analysis of the selected CDRs, its charts and the maps of every group are rendered at full size, so it can take a minute or more. The document downloads when it is ready.`,
      `Preparing the ${label} document`);
    try {
      const response = await fetch(`/api/network-insights/export/${kind}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestBody(analysis?.maps?.operator || '')),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `Unable to export the ${label} summary.`);
      }
      const disposition = response.headers.get('content-disposition') || '';
      const name = /filename\*?=(?:UTF-8'')?"?([^";]+)/i.exec(disposition)?.[1];
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = name ? decodeURIComponent(name) : `Summary Network Insights.${kind === 'word' ? 'docx' : 'pptx'}`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 10000);
      status(`Summary Network Insights ${label} downloaded.`, 'done');
    } catch (error) {
      status(error.message, 'error');
      hideProgress();
      globalThis.showInfoDialog?.(error.message, {tone: 'error', title: 'The document could not be generated'});
    } finally {
      button.disabled = false; button.classList.remove('is-busy');
      hideProgress();
    }
  }));

  const delta = (value, unit, betterHigher) => {
    if (value === null || value === undefined) return '';
    const improved = betterHigher ? value > 0 : value < 0;
    const sign = value > 0 ? '+' : '';
    return `<span class="ni-delta ${value === 0 ? '' : improved ? 'is-better' : 'is-worse'}">${sign}${number(value)}${unit}</span>`;
  };
  const sectionTitle = section => `<h3 class="ni-technology-title">${escapeHtml(section.technology_label)} <span>Low coverage below ${escapeHtml(section.coverage_threshold)} dBm · high interference below ${escapeHtml(section.interference_threshold)} dB</span></h3>`;
  const renderOverview = () => {
    const host = $('ni-overview');
    host.replaceChildren();
    for (const section of sections()) {
      if (multipleSections()) host.insertAdjacentHTML('beforeend', sectionTitle(section));
      renderOverviewCards(host, section);
    }
  };
  const renderOverviewCards = (host, section) => {
    for (const row of section.overview) {
      const colour = analysis.colours[row.operator] || '#6D46A8';
      const deltas = row.deltas || {};
      const card = document.createElement('article');
      card.className = 'ni-operator-card';
      card.style.setProperty('--ni-operator', colour);
      card.innerHTML = `<h3>${escapeHtml(row.operator)}</h3>
        <dl>
          <div><dt>Median RSRP</dt><dd>${number(row.rsrp_median)} dBm ${delta(deltas.rsrp_median, ' dB', true)}</dd></div>
          <div><dt>Low coverage</dt><dd>${number(row.low_coverage_share)}% ${delta(deltas.low_coverage_share, ' pp', false)}</dd></div>
          <div><dt>Median SINR</dt><dd>${number(row.sinr_median)} dB ${delta(deltas.sinr_median, ' dB', true)}</dd></div>
          <div><dt>High interference</dt><dd>${number(row.high_interference_share)}% ${delta(deltas.high_interference_share, ' pp', false)}</dd></div>
          <div><dt>Observed eNodeBs</dt><dd>${integer(row.observed_enodebs)}</dd></div>
          <div><dt>Samples</dt><dd>${integer(row.samples)}</dd></div>
        </dl>`;
      host.append(card);
    }
  };
  const classBar = classes => `<span class="ni-class-bar">${(classes || []).map(item =>
    `<span style="width:${item.share}%;background:${item.colour}" title="${escapeHtml(item.label)}: ${number(item.share)}%"></span>`).join('')}</span>`;
  // RF Quality: CDFs and table per technology (LTE and NR separately with LTE+NR).
  const renderRfSections = () => {
    const host = $('ni-rf-sections');
    host.innerHTML = sections().map(section => `<section class="ni-technology-section">
      ${multipleSections() ? sectionTitle(section) : ''}
      <div class="ni-chart-grid">
        <div class="ni-chart-card"><canvas id="ni-${section.technology}-rsrp-cdf" role="img" aria-label="${escapeHtml(section.technology_label)} RSRP cumulative distribution"></canvas></div>
        <div class="ni-chart-card"><canvas id="ni-${section.technology}-sinr-cdf" role="img" aria-label="${escapeHtml(section.technology_label)} SINR cumulative distribution"></canvas></div>
      </div>
      <div class="table-wrap ni-table-wrap"><table class="ni-table">${rfTable(section)}</table></div>
    </section>`).join('');
    for (const section of sections()) {
      renderChart($(`ni-${section.technology}-rsrp-cdf`), section.charts.rsrp_cdf);
      renderChart($(`ni-${section.technology}-sinr-cdf`), section.charts.sinr_cdf);
    }
  };
  const rfTable = section => {
    const grouped = Boolean(section.rf_rows.some(row => row.group));
    return `<thead><tr><th>${escapeHtml(analysis.group_label || 'All samples')}</th>${grouped ? `<th>${escapeHtml(analysis.group_label)}</th>` : ''}<th>Samples</th><th>${escapeHtml(section.technology_label)} RSRP samples</th><th>Median RSRP</th><th>P10 RSRP</th><th>Low coverage</th><th>RSRP classes</th><th>Median SINR</th><th>P10 SINR</th><th>High interference</th><th>SINR classes</th></tr></thead>
    <tbody>${section.rf_rows.map(row => `<tr>
      <td><span class="ni-swatch" style="background:${analysis.colours[row.operator] || '#6D46A8'}"></span>${escapeHtml(row.operator)}</td>
      ${grouped ? `<td>${escapeHtml(row.group)}</td>` : ''}
      <td class="num">${integer(row.samples)}</td><td class="num">${integer(row.rsrp_samples)}</td><td class="num">${number(row.rsrp_median)}</td><td class="num">${number(row.rsrp_p10)}</td>
      <td class="num">${number(row.low_coverage_share)}%</td><td>${classBar(row.rsrp_classes)}</td>
      <td class="num">${number(row.sinr_median)}</td><td class="num">${number(row.sinr_p10)}</td>
      <td class="num">${number(row.high_interference_share)}%</td><td>${classBar(row.sinr_classes)}</td></tr>`).join('')}</tbody>`;
  };

  // In-chart zoom controls, as in PPT Dashboards: zoom out/in, level, reset
  // and pan arrows while zoomed. Dragging a rectangle also zooms.
  const panPaths = {left: 'M15 5 8 12l7 7', right: 'm9 5 7 7-7 7', up: 'M5 15 12 8l7 7', down: 'm5 9 7 7 7-7'};
  const renderChart = (canvas, payload) => {
    if (!canvas) return;
    globalThis.renderDashboardChart(canvas, payload);
    const card = canvas.parentElement;
    if (!card || card.querySelector(':scope > .ni-chart-zoom')) return;
    const button = (text, title, className = '') => {
      const element = document.createElement('button');
      element.type = 'button'; element.className = `ni-chart-zoom-button ${className}`.trim();
      element.title = title; element.setAttribute('aria-label', title); element.textContent = text;
      return element;
    };
    const controls = document.createElement('div');
    controls.className = 'ni-chart-zoom'; controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', 'Chart zoom');
    const zoomOut = button('−', 'Zoom out');
    const level = document.createElement('output'); level.className = 'ni-chart-zoom-level';
    const zoomIn = button('+', 'Zoom in');
    const reset = button('1:1', 'Reset zoom', 'ni-chart-zoom-reset');
    controls.append(zoomOut, level, zoomIn, reset);
    const pans = Object.entries(panPaths).map(([direction, path]) => {
      const pan = button('', `Move view ${direction}`, `ni-chart-pan ni-chart-pan-${direction}`);
      pan.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
      pan.onclick = event => { event.stopPropagation(); globalThis.panDashboardChart?.(canvas, direction); sync(); };
      return [direction, pan];
    });
    const sync = () => {
      const zoom = Math.max(1, Number(globalThis.getDashboardChartZoom?.(canvas)) || 1);
      level.textContent = `${Math.round(zoom * 100)}%`;
      zoomOut.disabled = reset.disabled = zoom <= 1; zoomIn.disabled = zoom >= 4;
      const state = globalThis.getDashboardChartPanState?.(canvas) || {};
      for (const [direction, pan] of pans) {
        pan.hidden = zoom <= 1;
        pan.disabled = !state[`canPan${direction[0].toUpperCase()}${direction.slice(1)}`];
      }
    };
    const apply = zoom => { globalThis.setDashboardChartZoom?.(canvas, Math.max(1, Math.min(4, zoom))); sync(); };
    zoomOut.onclick = event => { event.stopPropagation(); apply((globalThis.getDashboardChartZoom?.(canvas) || 1) - .25); };
    zoomIn.onclick = event => { event.stopPropagation(); apply((globalThis.getDashboardChartZoom?.(canvas) || 1) + .25); };
    reset.onclick = event => { event.stopPropagation(); apply(1); };
    canvas.addEventListener('dashboardchartzoom', sync);
    canvas.addEventListener('dashboardchartpan', sync);
    card.append(controls, ...pans.map(([, pan]) => pan));
    sync();
  };

  // A port of the server's OpenStreetMap tile geometry, used to zoom maps.
  const osmWorld = (latitude, longitude, zoom) => {
    const scale = 256 * 2 ** zoom;
    const bounded = Math.max(Math.min(latitude, 85.05112878), -85.05112878) * Math.PI / 180;
    return [(longitude + 180) / 360 * scale, (1 - Math.asinh(Math.tan(bounded)) / Math.PI) / 2 * scale];
  };
  const basemapFor = (lonLow, lonHigh, latLow, latHigh, base) => {
    for (let zoom = 18; zoom > 1; zoom -= 1) {
      const topLeft = osmWorld(latHigh, lonLow, zoom), bottomRight = osmWorld(latLow, lonHigh, zoom);
      const range = [Math.floor(topLeft[0] / 256), Math.floor(topLeft[1] / 256), Math.floor(bottomRight[0] / 256), Math.floor(bottomRight[1] / 256)];
      if ((range[2] - range[0] + 1) * (range[3] - range[1] + 1) <= 48) {
        return {...base, zoom, tile_range: range, world_bounds: [...topLeft, ...bottomRight]};
      }
    }
    return base;
  };
  const zoomMap = (kind, latitude, longitude) => {
    const payload = mapPayloads[kind];
    if (!payload || payload.type !== 'map') return;
    const span = Math.max(0.01, Number($('ni-grid').value) / 111_320 * 12);
    const domain = {x: [longitude - span * 1.6, longitude + span * 1.6], y: [latitude - span, latitude + span]};
    const pad = value => Math.max((value[1] - value[0]) * .06, .004);
    // About 24 grid squares span the zoomed height, so dots can approach their real size.
    const zoomed = {...payload, domain, point_radius: 12, basemap: basemapFor(domain.x[0] - pad(domain.x), domain.x[1] + pad(domain.x), domain.y[0] - pad(domain.y), domain.y[1] + pad(domain.y), payload.basemap)};
    globalThis.setDashboardChartZoom?.($(`ni-${kind}-map`), 1);
    globalThis.renderDashboardChart($(`ni-${kind}-map`), zoomed);
    $('ni-map-note').textContent = `Zoomed to ${number(latitude, 4)}, ${number(longitude, 4)}.`;
  };
  const hotspotTable = (kind, rows, unit) => {
    if (!rows.length) return '<tbody><tr><td class="form-note">No grid square has most samples below the threshold.</td></tr></tbody>';
    return `<thead><tr><th>Area</th><th>Region</th><th>Samples</th><th>Mean</th><th>Below</th></tr></thead><tbody>${rows.map(row => `<tr>
      <td><button type="button" class="ni-zoom" data-kind="${kind}" data-latitude="${row.latitude}" data-longitude="${row.longitude}" title="Zoom the map to ${number(row.latitude, 4)}, ${number(row.longitude, 4)}">${escapeHtml(row.city || `${number(row.latitude, 3)}, ${number(row.longitude, 3)}`)}</button></td>
      <td>${escapeHtml(row.region || '—')}</td><td class="num">${integer(row.samples)}</td>
      <td class="num">${number(row.mean)} ${unit}</td><td class="num">${number(row.bad_share)}%</td></tr>`).join('')}</tbody>`;
  };
  // Coverage and interference maps per technology, for one shared Group.
  const renderMaps = () => {
    const maps = analysis.maps;
    const selector = $('ni-map-operator');
    // Follow the displayed table order rather than the map payload's source order.
    const availableGroups = new Set(sections().flatMap(section => section.maps.operators));
    const orderedGroups = [...new Set(analysis.rf_rows.map(row => row.operator))]
      .filter(group => availableGroups.has(group));
    const displayedGroups = new Set(orderedGroups);
    orderedGroups.push(...[...availableGroups].filter(group => !displayedGroups.has(group))
      .sort((left, right) => left.localeCompare(right, undefined, {sensitivity: 'base', numeric: true})));
    selector.replaceChildren(...orderedGroups.map(operator => {
      const option = document.createElement('option'); option.value = operator; option.textContent = operator; option.selected = operator === maps.operator; return option;
    }));
    for (const key of Object.keys(mapPayloads)) delete mapPayloads[key];
    $('ni-map-sections').innerHTML = sections().map(section => {
      const radio = section.technology;
      const label = escapeHtml(section.technology_label);
      return `<section class="ni-technology-section">
        ${multipleSections() ? sectionTitle(section) : ''}
        <div class="ni-map-grid">
          <section class="ni-map-card"><h3>${label} Coverage (mean RSRP per grid square)</h3><div class="ni-chart-card ni-map-canvas"><canvas id="ni-${radio}-coverage-map" role="img" aria-label="${label} coverage map"></canvas></div>
            <h4>Weakest coverage areas</h4><div class="table-wrap ni-hotspot-wrap"><table class="ni-table ni-hotspots">${hotspotTable(`${radio}-coverage`, section.maps.coverage_hotspots, 'dBm')}</table></div></section>
          <section class="ni-map-card"><h3>${label} Interference (mean SINR per grid square)</h3><div class="ni-chart-card ni-map-canvas"><canvas id="ni-${radio}-interference-map" role="img" aria-label="${label} interference map"></canvas></div>
            <h4>Highest interference areas</h4><div class="table-wrap ni-hotspot-wrap"><table class="ni-table ni-hotspots">${hotspotTable(`${radio}-interference`, section.maps.interference_hotspots, 'dB')}</table></div></section>
        </div>
      </section>`;
    }).join('');
    for (const section of sections()) {
      for (const kind of ['coverage', 'interference']) {
        const key = `${section.technology}-${kind}`;
        mapPayloads[key] = section.maps[kind];
        renderChart($(`ni-${key}-map`), section.maps[kind]);
      }
    }
    $('ni-map-note').textContent = `${maps.operator} · grid ${number(maps.coverage_grid_metres, 0)} m${maps.coverage_grid_metres !== Number($('ni-grid').value) ? ' (coarsened to keep the map readable)' : ''}.`;
  };
  let clusterInventories = null;
  const renderSites = () => {
    const observed = $('ni-sites-source').value === 'observed';
    const missing = analysis?.missing_inventory_operators || [];
    $('ni-sites-pending').hidden = !observed || !missing.length;
    $('ni-sites-pending').innerHTML = missing.length
      ? `<strong>Pending input:</strong> site inventories for ${missing.map(escapeHtml).join(', ')}.` : '';
    $('ni-sites-note').hidden = !observed;
    $('ni-sites-inventory-note').hidden = observed;
    $('ni-inventory-totals').hidden = observed;
    const table = $('ni-sites-table');
    if (!observed) {
      const rows = clusterInventories?.rows || [];
      table.innerHTML = rows.length
        ? `<thead><tr><th>Operator</th><th>Inventory sites</th><th>Inventory cells</th></tr></thead><tbody>${rows.map(row => `<tr><td>${escapeHtml(row.operator)}</td><td class="num">${integer(row.sites)}</td><td class="num">${integer(row.cells)}</td></tr>`).join('')}</tbody>`
        : '<tbody><tr><td class="form-note">No supported site/cell inventory is available.</td></tr></tbody>';
      return;
    }
    if (!analysis) {
      table.innerHTML = '<tbody><tr><td class="form-note">No analysis yet.</td></tr></tbody>';
      return;
    }
    const grouped = Boolean(analysis.rf_rows.some(row => row.group));
    const technology = multipleSections();
    table.innerHTML = `<thead><tr><th>${escapeHtml(analysis.group_label || 'All samples')}</th>${grouped ? `<th>${escapeHtml(analysis.group_label)}</th>` : ''}${technology ? '<th>Technology</th>' : ''}<th>Observed eNodeBs</th><th>Observed cells</th><th>Samples</th><th>Samples per eNodeB</th></tr></thead><tbody>${analysis.rf_rows.map(row => `<tr>
      <td><span class="ni-swatch" style="background:${analysis.colours[row.operator] || '#6D46A8'}"></span>${escapeHtml(row.operator)}</td>${grouped ? `<td>${escapeHtml(row.group)}</td>` : ''}${technology ? `<td>${escapeHtml(row.technology || '')}</td>` : ''}
      <td class="num">${integer(row.observed_enodebs)}</td><td class="num">${integer(row.observed_cells)}</td><td class="num">${integer(row.samples)}</td>
      <td class="num">${row.observed_enodebs ? number(row.samples / row.observed_enodebs) : '—'}</td></tr>`).join('')}</tbody>`;
  };
  const renderLicensed = summary => {
    const host = $('ni-licensed');
    const classes = config.band_classes || [];
    if (!summary.length) {
      host.innerHTML = `<p class="ni-pending-box"><strong>Pending input.</strong> No licensed spectrum is configured for this workspace yet. ${config.can_edit ? 'Add each Operator\'s holdings (band, duplex, class and MHz) in <a href="/workspace-config#spectrum-holdings">Workspace Config → Mappings &amp; Reference Data → Spectrum Holdings</a>.' : 'Ask an editor to add them in Workspace Config.'}</p>`;
      return;
    }
    const maximum = Math.max(...summary.map(row => row.total), 1);
    host.innerHTML = `<table class="ni-table"><thead><tr><th>Operator</th>${classes.map(name => `<th>${escapeHtml(name)} (MHz)</th>`).join('')}<th>Total (MHz)</th><th></th></tr></thead><tbody>${summary.map(row => `<tr>
      <td>${escapeHtml(row.operator)}</td>${classes.map(name => `<td class="num">${number(row[name])}</td>`).join('')}<td class="num"><strong>${number(row.total)}</strong></td>
      <td class="ni-spectrum-bar-cell"><span class="ni-class-bar ni-spectrum-bar" style="width:${row.total / maximum * 100}%">${classes.map((name, index) => `<span style="width:${row.total ? row[name] / row.total * 100 : 0}%;background:${['#5C940D', '#1C7ED6', '#C2255C'][index]}" title="${escapeHtml(name)}: ${number(row[name])} MHz"></span>`).join('')}</span></td></tr>`).join('')}</tbody></table>`;
  };
  const renderSpectrum = () => {
    renderLicensed(analysis.spectrum.licensed);
    const table = $('ni-observed-spectrum');
    const rows = analysis.spectrum.observed;
    if (!rows.length) { table.innerHTML = '<tbody><tr><td class="form-note">The selected CDRs report no serving bands.</td></tr></tbody>'; return; }
    table.innerHTML = `<thead><tr><th>${escapeHtml(analysis.group_label || 'All samples')}</th><th>Technology</th><th>Band</th><th>Frequency</th><th>Duplex</th><th>Class</th><th>Samples</th><th>Share</th><th>Typical DL bandwidth</th></tr></thead><tbody>${rows.map(row => `<tr>
      <td><span class="ni-swatch" style="background:${analysis.colours[row.operator] || '#6D46A8'}"></span>${escapeHtml(row.operator)}</td><td>${escapeHtml(row.technology)}</td><td>${escapeHtml(row.band)}</td>
      <td class="num">${row.frequency_mhz ? `${integer(row.frequency_mhz)} MHz` : '—'}</td><td>${escapeHtml(row.duplex || '—')}</td><td>${escapeHtml(row.band_class || '—')}</td>
      <td class="num">${integer(row.samples)}</td><td><span class="ni-share"><span style="width:${row.share}%"></span></span> ${number(row.share)}%</td>
      <td class="num">${row.typical_bandwidth_mhz ? `${number(row.typical_bandwidth_mhz, 0)} MHz` : '—'}</td></tr>`).join('')}</tbody>`;
  };
  const render = () => {
    if (!analysis) return;
    renderOverview();
    renderRfSections();
    renderMaps();
    renderSites();
    renderSpectrum();
  };

  // Sites/Cells tables: complete inventories or cells observed in the CDRs.
  const siteTableTitle = source => source === 'observed' ? 'Observed Sites/Cells (from CDRs)' : 'Full Sites/Cells Inventory';
  const renderInventory = inventory => {
    const lastPage = Math.max(0, Math.ceil(inventory.total_rows / inventory.page_size) - 1);
    const filters = inventory.filters || {};
    const active = Object.keys(filters).length;
    return `<section class="ni-inventory" data-ni-inventory="${escapeHtml(inventory.operator)}" data-ni-operator-label="${escapeHtml(inventory.operator_label || inventory.operator)}" data-ni-source="${escapeHtml(inventory.source || 'inventory')}" data-ni-filters="${escapeHtml(JSON.stringify(filters))}">
      <h3>${escapeHtml(inventory.operator_label || inventory.operator)} · ${siteTableTitle(inventory.source)}</h3>
      <div class="ni-map-toolbar">
        <button type="button" class="ni-secondary-action ni-export-action" data-ni-inventory-export>Export CSV</button>
        ${active ? `<button type="button" class="ni-secondary-action" data-ni-filters-clear>Clear ${integer(active)} filter${active === 1 ? '' : 's'}</button>` : ''}
        <button type="button" class="ni-secondary-action ni-page-action" data-ni-inventory-page="${inventory.page - 1}" ${inventory.page === 0 ? 'disabled' : ''}>Previous</button>
        <span class="form-note">Page ${integer(inventory.page + 1)} of ${integer(lastPage + 1)} · ${integer(inventory.total_rows)} rows · ${integer(inventory.columns.length)} columns</span>
        <button type="button" class="ni-secondary-action ni-page-action" data-ni-inventory-page="${inventory.page + 1}" ${inventory.page >= lastPage ? 'disabled' : ''}>Next</button>
      </div>
      <div class="table-wrap ni-table-wrap"><table class="ni-table"><thead><tr>${inventory.columns.map(column => `<th${inventory.key_columns.includes(column) ? ' class="ni-inventory-key-column"' : ''}><span class="ni-column-head">${escapeHtml(column)}<button type="button" class="ni-column-filter${filters[column] ? ' is-active' : ''}" data-ni-filter-column="${escapeHtml(column)}" title="Filter ${escapeHtml(column)}" aria-label="Filter ${escapeHtml(column)}">▾</button></span></th>`).join('')}</tr></thead>
      <tbody>${inventory.rows.map(row => `<tr>${row.map((value, index) => `<td${inventory.key_columns.includes(inventory.columns[index]) ? ' class="ni-inventory-key-column"' : ''}>${escapeHtml(value ?? '')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${inventory.columns.length || 1}" class="form-note">${active ? 'No rows match the column filters.' : 'No rows.'}</td></tr>`}</tbody></table></div>
    </section>`;
  };

  let inventorySelection = null;
  let displayedDeploymentGroup = '';
  const isSiteTable = group => group === 'inventory' || group === 'observed';
  const cardFilters = card => { try { return JSON.parse(card.dataset.niFilters || '{}'); } catch { return {}; } };
  const fileName = response => {
    const disposition = response.headers.get('content-disposition') || '';
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    return match ? decodeURIComponent(match[1]) : '';
  };
  const downloadDeploymentCsv = async (button, operator = '', filters = {}) => {
    if (button.disabled) return;
    const selection = inventorySelection;
    const group = displayedDeploymentGroup;
    button.disabled = true;
    try {
      const response = isSiteTable(group)
        ? await fetch('/api/network-insights/sites/export', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...selection, operator, filters}),
        })
        : await fetch(`/api/network-insights/deployment/export-all?group=${encodeURIComponent(group)}`);
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail || 'Unable to export the deployment tables.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName(response) || `network-deployment-${group}.csv`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      $('ni-deployment-status').textContent = error.message;
    } finally {
      if (displayedDeploymentGroup === group && !deploymentController?.signal.aborted) button.disabled = false;
    }
  };
  // Reload one table with its page and column filters.
  const reloadSiteTable = async (card, page, filters) => {
    const controller = deploymentController;
    const controls = [...card.querySelectorAll('button')].map(control => [control, control.disabled]);
    controls.forEach(([control]) => { control.disabled = true; });
    try {
      const response = await fetch('/api/network-insights/sites/page', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
        body: JSON.stringify({...inventorySelection, operator: card.dataset.niInventory, page, filters}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Unable to load the table page.');
      if (deploymentController === controller && card.isConnected) {
        card.outerHTML = renderInventory({...payload, operator_label: card.dataset.niOperatorLabel});
      }
    } catch (error) {
      if (error.name !== 'AbortError' && deploymentController === controller && card.isConnected) {
        $('ni-deployment-status').textContent = error.message;
        controls.forEach(([control, disabled]) => { control.disabled = disabled; });
      }
    }
  };

  // Excel-style column filter: the values of the column under the other filters.
  let filterMenu = null;
  let placeFilterMenu = null;
  const closeFilterMenu = () => { filterMenu?.remove(); filterMenu = null; placeFilterMenu = null; };
  const openFilterMenu = async (card, button) => {
    closeFilterMenu();
    const column = button.dataset.niFilterColumn;
    const filters = cardFilters(card);
    const menu = document.createElement('section');
    menu.className = 'excel-column-filter-menu ni-filter-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filter ${column}`);
    menu.innerHTML = `<p class="form-note">Loading values of ${escapeHtml(column)}…</p>`;
    document.body.append(menu);
    filterMenu = menu;
    // The menu is fixed to the viewport: place it under its column button again on every scroll.
    const place = () => {
      const bounds = button.getBoundingClientRect();
      if (!button.isConnected || bounds.bottom < 0 || bounds.top > window.innerHeight) { closeFilterMenu(); return; }
      const width = Math.min(300, window.innerWidth - 20);
      menu.style.width = `${width}px`;
      menu.style.left = `${Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10))}px`;
      const below = bounds.bottom + 5;
      const height = menu.offsetHeight;
      menu.style.top = `${below + height <= window.innerHeight - 10 ? below : Math.max(10, bounds.top - height - 5)}px`;
    };
    placeFilterMenu = place;
    place();
    try {
      const response = await fetch('/api/network-insights/sites/values', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...inventorySelection, operator: card.dataset.niInventory, filters, column}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Unable to load the column values.');
      if (filterMenu !== menu) return;
      const selected = new Set(filters[column] || payload.values.map(item => item.value));
      menu.innerHTML = `<strong class="ni-filter-title">${escapeHtml(column)}</strong>
        <input type="search" placeholder="Search values" autocomplete="off" aria-label="Search values of ${escapeHtml(column)}">
        <div class="excel-column-filter-toolbar"><button type="button" data-ni-filter-all>Select all</button><button type="button" data-ni-filter-none>Clear</button></div>
        <div class="excel-column-filter-options">${payload.values.map(item => `<label><input type="checkbox" value="${escapeHtml(item.value)}" ${selected.has(item.value) ? 'checked' : ''}><span>${item.value === '' ? '(Blanks)' : escapeHtml(item.value)}</span><small>${integer(item.count)}</small></label>`).join('') || '<p class="form-note">No values.</p>'}</div>
        ${payload.truncated ? '<p class="form-note">Showing the first 2,000 values; search to narrow them.</p>' : ''}
        <div class="excel-column-filter-footer"><button type="button" data-ni-filter-cancel>Cancel</button><button type="button" data-ni-filter-reset>Remove filter</button><button type="button" data-ni-filter-apply>Apply</button></div>`;
      place();
      const boxes = () => [...menu.querySelectorAll('.excel-column-filter-options input')];
      const visible = () => boxes().filter(box => !box.closest('label').hidden);
      const search = menu.querySelector('input[type="search"]');
      // Typing filters the listed values; Select all and Clear act on the listed values.
      search.addEventListener('input', () => {
        const query = search.value.trim().toLocaleLowerCase();
        boxes().forEach(box => {
          const text = box.closest('label').querySelector('span').textContent.toLocaleLowerCase();
          box.closest('label').hidden = Boolean(query) && !text.includes(query);
        });
      });
      menu.querySelector('[data-ni-filter-all]').addEventListener('click', () => visible().forEach(box => { box.checked = true; }));
      menu.querySelector('[data-ni-filter-none]').addEventListener('click', () => visible().forEach(box => { box.checked = false; }));
      menu.querySelector('[data-ni-filter-cancel]').addEventListener('click', closeFilterMenu);
      menu.querySelector('[data-ni-filter-reset]').addEventListener('click', () => {
        delete filters[column];
        closeFilterMenu();
        void reloadSiteTable(card, 0, filters);
      });
      menu.querySelector('[data-ni-filter-apply]').addEventListener('click', () => {
        const chosen = boxes().filter(box => box.checked).map(box => box.value);
        if (chosen.length === boxes().length && !payload.truncated) delete filters[column];
        else filters[column] = chosen;
        closeFilterMenu();
        void reloadSiteTable(card, 0, filters);
      });
      requestAnimationFrame(() => search.focus());
    } catch (error) {
      if (filterMenu === menu) menu.innerHTML = `<p class="form-note">${escapeHtml(error.message)}</p>`;
    }
  };
  document.addEventListener('pointerdown', event => {
    if (filterMenu && !filterMenu.contains(event.target) && !event.target.closest('[data-ni-filter-column]')) closeFilterMenu();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeFilterMenu(); });
  window.addEventListener('resize', closeFilterMenu);
  document.addEventListener('scroll', event => {
    if (placeFilterMenu && !filterMenu?.contains(event.target)) placeFilterMenu();
  }, {capture: true, passive: true});

  $('ni-deployment-export-all').addEventListener('click', event => { void downloadDeploymentCsv(event.currentTarget); });
  $('ni-deployment').addEventListener('click', async event => {
    const card = event.target.closest('[data-ni-inventory]');
    if (!card || !inventorySelection) return;
    const filterButton = event.target.closest('[data-ni-filter-column]');
    if (filterButton) { void openFilterMenu(card, filterButton); return; }
    if (event.target.closest('[data-ni-filters-clear]')) { void reloadSiteTable(card, 0, {}); return; }
    const exportButton = event.target.closest('[data-ni-inventory-export]');
    if (exportButton) {
      void downloadDeploymentCsv(exportButton, card.dataset.niInventory, cardFilters(card));
      return;
    }
    const button = event.target.closest('[data-ni-inventory-page]');
    if (!button || button.disabled) return;
    void reloadSiteTable(card, Number(button.dataset.niInventoryPage), cardFilters(card));
  });

  let deploymentController = null;
  const loadDeployment = async () => {
    deploymentController?.abort();
    const controller = new AbortController();
    deploymentController = controller;
    const group = $('ni-deployment-group').value;
    const host = $('ni-deployment');
    const note = $('ni-deployment-status');
    $('ni-deployment-export-all').disabled = true;
    inventorySelection = null;
    if (!(config.inventories || []).length) {
      host.innerHTML = '<p class="ni-pending-box"><strong>Pending input.</strong> Upload the Vodafone or Three cell inventories as Vendor mapping datasets in Workspace to analyse NNS, eMOCN scenarios, host networks and RAN vendors.</p>';
      return;
    }
    note.textContent = 'Loading the cell inventories…';
    host.querySelectorAll('button').forEach(button => { button.disabled = true; });
    const timeout = setTimeout(() => controller.abort(), 120000);
    try {
      const selection = isSiteTable(group) ? {...requestBody(), source: group} : null;
      const response = isSiteTable(group)
        ? await fetch('/api/network-insights/sites/tables', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(selection), signal: controller.signal,
        })
        : await fetch(`/api/network-insights/deployment?group=${encodeURIComponent(group)}`, {signal: controller.signal});
      const payload = await response.json();
      if (deploymentController !== controller) return;
      if (!response.ok) throw new Error(payload.detail || 'Unable to load the cell inventories.');
      displayedDeploymentGroup = group;
      if (isSiteTable(group)) {
        inventorySelection = selection;
        $('ni-deployment-export-all').disabled = !payload.tables.length;
        host.innerHTML = payload.tables.map(renderInventory).join('') || '<p class="form-note">No table matches the selected operators.</p>';
        note.textContent = group === 'observed'
          ? 'Sites and LTE cells observed in the selected CDRs, filtered by the Analysis Selection (CDRs, Operator, Operator_Vendor, Vendor, Region, Cluster, City and Campaign). Use ▾ on a column to filter it; CSV exports every matching row.'
          : 'Complete uploaded inventories, filtered by Operator, Operator_Vendor, Vendor, Region, Cluster, City and Technology. CDR selection, NR Mode and Campaigns do not restrict inventory rows. Use ▾ on a column to filter it; CSV exports every matching row and column.';
        return;
      }
      $('ni-deployment-export-all').disabled = !payload.inventories.length;
      inventorySelection = null;
      host.innerHTML = payload.inventories.map(inventory => {
        const maximum = inventory.rows.reduce((maximum, row) => Math.max(maximum, row.sites), 1);
        const available = inventory.available_groups.includes(group);
        return `<section class="ni-inventory"><h3>${escapeHtml(inventory.operator)} <span>${escapeHtml(inventory.file_name)}</span></h3>
          <a class="ghost-link ni-export-action" href="/api/network-insights/deployment/${inventory.id}/export?group=${encodeURIComponent(group)}" download>Export CSV</a>
          ${available ? '' : `<p class="form-note">This inventory has no ${escapeHtml(payload.group_label)} column; totals are shown instead.</p>`}
          <table class="ni-table"><thead><tr><th>${escapeHtml(available ? payload.group_label : 'Inventory')}</th><th>Sites</th><th>Cells</th><th></th></tr></thead><tbody>${inventory.rows.map(row => `<tr>
            <td>${escapeHtml(row.group)}</td><td class="num">${integer(row.sites)}</td><td class="num">${integer(row.cells)}</td>
            <td><span class="ni-share"><span style="width:${row.sites / maximum * 100}%"></span></span></td></tr>`).join('')}</tbody></table></section>`;
      }).join('');
      note.textContent = 'Sites and cells counted from the uploaded cell inventories (distinct site and cell identifiers).';
    } catch (error) {
      if (deploymentController !== controller) return;
      note.textContent = error.name === 'AbortError'
        ? 'Loading the inventories timed out. Change the grouping or try again.' : error.message;
    } finally {
      clearTimeout(timeout);
    }
  };

  const loadClusterInventories = async () => {
    try {
      const response = await fetch('/api/network-insights/cluster-inventories');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Unable to load site inventories.');
      clusterInventories = payload;
      $('ni-inventory-totals').innerHTML = payload.rows.map(row =>
        `<article class="ni-inventory-total"><span>${escapeHtml(row.operator)} inventory</span><div class="ni-inventory-site-count"><strong>${integer(row.sites)}</strong><small>sites</small></div><small>${integer(row.cells)} cells</small></article>`).join('');
      renderSites();
    } catch (error) {
      if ($('ni-sites-source').value === 'inventory') $('ni-sites-table').innerHTML = `<tbody><tr><td class="form-note">${escapeHtml(error.message)}</td></tr></tbody>`;
    }
  };
  $('ni-sites-source').onchange = () => { renderSites(); if (!clusterInventories) void loadClusterInventories(); };
  renderSites();
  void loadClusterInventories();

  const rememberSelection = () => {
    const filters = Object.fromEntries(filterNames.map(field => {
      const id = `ni-${field}`;
      return [id, $(id).options.length ? filterValues(id) : savedSelection.filters?.[id] || []];
    }));
    savedSelection = {
      controls: Object.fromEntries(selectionControls.map(id => [id,
        $(id).multiple ? selectedValues(id) : $(id).value])),
      datasets: selectedDatasets(), filters,
      map_group: $('ni-map-operator').value || savedSelection.map_group || '',
    };
    try { if (storageKey) localStorage.setItem(storageKey, JSON.stringify(savedSelection)); } catch {}
  };
  $('network-insights').addEventListener('change', rememberSelection);
  let inventoryRefreshTimer = null;
  const refreshInventory = () => {
    if (!isSiteTable($('ni-deployment-group').value)) return;
    clearTimeout(inventoryRefreshTimer);
    deploymentController?.abort();
    $('ni-deployment-export-all').disabled = true;
    $('ni-deployment').querySelectorAll('button').forEach(button => { button.disabled = true; });
    inventoryRefreshTimer = setTimeout(() => { void loadDeployment(); }, 150);
  };
  $('network-insights').addEventListener('change', event => {
    if (event.target.closest('.ni-selection-panel')) refreshInventory();
  });

  $('ni-technology').onchange = syncTechnologyGrouping;
  $('ni-nr-mode').onchange = () => { renderDatasets(); scheduleFilterOptions(); };
  $('ni-datasets').addEventListener('change', scheduleFilterOptions);
  // Keep the map Operator across analyses when it is still part of the selection.
  $('ni-analyse').onclick = () => { void analyse($('ni-map-operator').value || savedSelection.map_group || ''); };
  $('ni-map-operator').onchange = () => { void analyse($('ni-map-operator').value || savedSelection.map_group || ''); };
  $('ni-map-reset').onclick = () => {
    for (const [kind, payload] of Object.entries(mapPayloads)) {
      if (!payload || !$(`ni-${kind}-map`)) continue;
      globalThis.setDashboardChartZoom?.($(`ni-${kind}-map`), 1);
      globalThis.renderDashboardChart($(`ni-${kind}-map`), payload);
    }
    if (analysis) $('ni-map-note').textContent = `${analysis.maps.operator} · whole area.`;
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('.ni-zoom');
    if (button) zoomMap(button.dataset.kind, Number(button.dataset.latitude), Number(button.dataset.longitude));
  });
  $('ni-deployment-group').onchange = () => { void loadDeployment(); };
  renderDatasets();
  void loadFilterOptions().then(showLastAnalysis);
  void loadDeployment();
})();
