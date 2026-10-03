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
    'ni-interference-threshold', 'ni-grid', 'ni-deployment-group'];
  for (const id of selectionControls) {
    const control = $(id);
    const value = savedSelection.controls?.[id];
    if (value === undefined) continue;
    if (control.multiple && Array.isArray(value)) {
      for (const option of control.options) option.selected = value.includes(option.value);
      control.dispatchEvent(new Event('multiselect:options-updated'));
    } else if (control.tagName === 'SELECT') {
      if ([...control.options].some(option => option.value === String(value))) control.value = value;
    } else if (Number.isFinite(Number(value))) control.value = value;
  }
  const pendingFilterRestore = new Map(Object.entries(savedSelection.filters || {})
    .filter(([, values]) => Array.isArray(values)));
  let restoreDatasets = true;
  const syncTechnologyGrouping = () => {
    const control = $('ni-group');
    const existing = [...control.options].find(option => option.value === 'technology');
    if ($('ni-technology').value === 'lte_nr') {
      if (!existing) control.add(new Option('Technology', 'technology'), [...control.options].find(option => option.value === 'campaign') || null);
    } else if (existing) existing.remove();
    control.dispatchEvent(new Event('multiselect:options-updated'));
  };
  syncTechnologyGrouping();
  const kinds = [['data', 'CDR Data'], ['voice', 'CDR Voice'], ['speech', 'CDR Speech']];
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const number = (value, digits = 1) => (value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits));
  const integer = value => (Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-US') : '—');
  let analysis = null;
  let analysing = 0;
  const mapPayloads = {coverage: null, interference: null};

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
      group.innerHTML = `<h3>${escapeHtml(label)} <span>(${escapeHtml(nrMode)})</span></h3>`;
      if (!rows.length) group.insertAdjacentHTML('beforeend', '<p class="form-note">No ready CDRs.</p>');
      const restored = restoreDatasets && Array.isArray(savedSelection.datasets?.[kind]) ? new Set(savedSelection.datasets[kind].map(Number)) : null;
      rows.forEach((row, index) => {
        const option = document.createElement('label');
        option.className = 'ni-dataset-option';
        option.innerHTML = `<input type="checkbox" value="${row.id}" data-kind="${kind}"${(restored ? restored.has(Number(row.id)) : true) ? ' checked' : ''}><span>${escapeHtml(row.file_name)} · ${integer(row.row_count)} rows</span>`;
        group.append(option);
      });
      host.append(group);
    }
    restoreDatasets = false;
  };
  const selectedDatasets = () => Object.fromEntries(kinds.map(([kind]) => [kind,
    [...document.querySelectorAll(`#ni-datasets input[data-kind="${kind}"]:checked`)].map(input => Number(input.value))]));
  const selectedValues = id => [...$(id).selectedOptions].map(option => option.value);
  const allSelected = id => {
    const options = [...$(id).options].filter(option => option.value);
    return options.length > 0 && options.every(option => option.selected);
  };
  // An unfiltered selector (every value or none) sends no restriction.
  const filterValues = id => (allSelected(id) ? [] : selectedValues(id));
  const fillSelector = (id, values) => {
    const control = $(id);
    const restored = pendingFilterRestore.get(id);
    const previous = new Set(restored || selectedValues(id));
    const keepAll = restored ? !restored.length : !control.options.length || allSelected(id) || !previous.size;
    pendingFilterRestore.delete(id);
    control.dataset.multiselectNoValuesLabel = 'No values available';
    control.replaceChildren(...values.map(value => {
      const option = document.createElement('option');
      option.value = value; option.textContent = value;
      option.selected = keepAll || previous.has(value);
      return option;
    }));
    control.dispatchEvent(new Event('multiselect:options-updated'));
  };

  const filterNames = ['operators', 'vendors', 'regions', 'cities', 'campaigns'];
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
      };
      // Cached dimensions render independently of the first Vendor_Only lookup.
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
    technology: $('ni-technology').value,
    group: selectedValues('ni-group'),
    operators: filterValues('ni-operators'),
    vendors: filterValues('ni-vendors'),
    campaigns: filterValues('ni-campaigns'),
    regions: filterValues('ni-regions'),
    cities: filterValues('ni-cities'),
    coverage_threshold: Number($('ni-coverage-threshold').value),
    interference_threshold: Number($('ni-interference-threshold').value),
    grid_metres: Number($('ni-grid').value),
    min_samples: 3,
    map_operator: mapOperator,
  });

  const analyse = async (mapOperator = '') => {
    const request = ++analysing;
    const button = $('ni-analyse');
    button.disabled = true; button.classList.add('is-busy');
    status('Analysing the selected CDRs… The first analysis of a CDR copies its radio fields and can take a minute.', 'busy');
    try {
      const response = await fetch('/api/network-insights/analysis', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestBody(mapOperator)),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to analyse the selected CDRs.');
      if (request !== analysing) return;
      analysis = payload;
      fillFilterOptions(payload.options);
      render();
      const comparison = payload.comparison ? ` Changes compare ${payload.comparison.latest} with ${payload.comparison.previous}.` : '';
      status(`Analysed ${integer(payload.overview.reduce((total, row) => total + row.samples, 0))} samples (${payload.technology_label}).${comparison}${payload.warnings.length ? ` ${payload.warnings.join(' ')}` : ''}`, payload.warnings.length ? 'warning' : 'done');
    } catch (error) {
      if (request === analysing) status(error.message, 'error');
    } finally {
      if (request === analysing) { button.disabled = false; button.classList.remove('is-busy'); }
    }
  };

  const delta = (value, unit, betterHigher) => {
    if (value === null || value === undefined) return '';
    const improved = betterHigher ? value > 0 : value < 0;
    const sign = value > 0 ? '+' : '';
    return `<span class="ni-delta ${value === 0 ? '' : improved ? 'is-better' : 'is-worse'}">${sign}${number(value)}${unit}</span>`;
  };
  const renderOverview = () => {
    const host = $('ni-overview');
    host.replaceChildren();
    for (const row of analysis.overview) {
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
  const renderRfTable = () => {
    const table = $('ni-rf-table');
    const grouped = Boolean(analysis.rf_rows.some(row => row.group));
    table.querySelector('thead').innerHTML = `<tr><th>${escapeHtml(analysis.group_label || 'All samples')}</th>${grouped ? `<th>${escapeHtml(analysis.group_label)}</th>` : ''}<th>Samples</th><th>${escapeHtml(analysis.technology_label)} RSRP samples</th><th>Median RSRP</th><th>P10 RSRP</th><th>Low coverage</th><th>RSRP classes</th><th>Median SINR</th><th>P10 SINR</th><th>High interference</th><th>SINR classes</th></tr>`;
    table.querySelector('tbody').innerHTML = analysis.rf_rows.map(row => `<tr>
      <td><span class="ni-swatch" style="background:${analysis.colours[row.operator] || '#6D46A8'}"></span>${escapeHtml(row.operator)}</td>
      ${grouped ? `<td>${escapeHtml(row.group)}</td>` : ''}
      <td class="num">${integer(row.samples)}</td><td class="num">${integer(row.rsrp_samples)}</td><td class="num">${number(row.rsrp_median)}</td><td class="num">${number(row.rsrp_p10)}</td>
      <td class="num">${number(row.low_coverage_share)}%</td><td>${classBar(row.rsrp_classes)}</td>
      <td class="num">${number(row.sinr_median)}</td><td class="num">${number(row.sinr_p10)}</td>
      <td class="num">${number(row.high_interference_share)}%</td><td>${classBar(row.sinr_classes)}</td></tr>`).join('');
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
  const renderHotspots = (kind, rows, unit) => {
    const table = $(`ni-${kind}-hotspots`);
    if (!rows.length) { table.innerHTML = '<tbody><tr><td class="form-note">No grid square has most samples below the threshold.</td></tr></tbody>'; return; }
    table.innerHTML = `<thead><tr><th>Area</th><th>Region</th><th>Samples</th><th>Mean</th><th>Below</th></tr></thead><tbody>${rows.map(row => `<tr>
      <td><button type="button" class="ni-zoom" data-kind="${kind}" data-latitude="${row.latitude}" data-longitude="${row.longitude}" title="Zoom the map to ${number(row.latitude, 4)}, ${number(row.longitude, 4)}">${escapeHtml(row.city || `${number(row.latitude, 3)}, ${number(row.longitude, 3)}`)}</button></td>
      <td>${escapeHtml(row.region || '—')}</td><td class="num">${integer(row.samples)}</td>
      <td class="num">${number(row.mean)} ${unit}</td><td class="num">${number(row.bad_share)}%</td></tr>`).join('')}</tbody>`;
  };
  const renderMaps = () => {
    const maps = analysis.maps;
    const selector = $('ni-map-operator');
    // Follow the displayed table order rather than the map payload's source order.
    const availableGroups = new Set(maps.operators);
    const orderedGroups = [...new Set(analysis.rf_rows.map(row => row.operator))]
      .filter(group => availableGroups.has(group));
    const displayedGroups = new Set(orderedGroups);
    orderedGroups.push(...maps.operators.filter(group => !displayedGroups.has(group))
      .sort((left, right) => left.localeCompare(right, undefined, {sensitivity: 'base', numeric: true})));
    selector.replaceChildren(...orderedGroups.map(operator => {
      const option = document.createElement('option'); option.value = operator; option.textContent = operator; option.selected = operator === maps.operator; return option;
    }));
    mapPayloads.coverage = maps.coverage; mapPayloads.interference = maps.interference;
    globalThis.renderDashboardChart($('ni-coverage-map'), maps.coverage);
    globalThis.renderDashboardChart($('ni-interference-map'), maps.interference);
    renderHotspots('coverage', maps.coverage_hotspots, 'dBm');
    renderHotspots('interference', maps.interference_hotspots, 'dB');
    $('ni-map-note').textContent = `${maps.operator} · grid ${number(maps.coverage_grid_metres, 0)} m${maps.coverage_grid_metres !== Number($('ni-grid').value) ? ' (coarsened to keep the map readable)' : ''}.`;
  };
  const renderSites = () => {
    const table = $('ni-sites-table');
    const grouped = Boolean(analysis.rf_rows.some(row => row.group));
    table.innerHTML = `<thead><tr><th>${escapeHtml(analysis.group_label || 'All samples')}</th>${grouped ? `<th>${escapeHtml(analysis.group_label)}</th>` : ''}<th>Observed eNodeBs</th><th>Observed cells</th><th>Samples</th><th>Samples per eNodeB</th></tr></thead><tbody>${analysis.rf_rows.map(row => `<tr>
      <td><span class="ni-swatch" style="background:${analysis.colours[row.operator] || '#6D46A8'}"></span>${escapeHtml(row.operator)}</td>${grouped ? `<td>${escapeHtml(row.group)}</td>` : ''}
      <td class="num">${integer(row.observed_enodebs)}</td><td class="num">${integer(row.observed_cells)}</td><td class="num">${integer(row.samples)}</td>
      <td class="num">${row.observed_enodebs ? number(row.samples / row.observed_enodebs) : '—'}</td></tr>`).join('')}</tbody>`;
  };
  const renderLicensed = summary => {
    const host = $('ni-licensed');
    const classes = config.band_classes || [];
    if (!summary.length) {
      host.innerHTML = `<p class="ni-pending-box"><strong>Pending input.</strong> No licensed spectrum is configured for this workspace yet. ${config.can_edit ? 'Add each Operator\'s holdings (band, duplex, class and MHz) in <a href="/workspace-config#spectrum-holdings">Workspace Config → Operator &amp; Vendor Maps → Spectrum Holdings</a>.' : 'Ask an editor to add them in Workspace Config.'}</p>`;
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
    globalThis.renderDashboardChart($('ni-rsrp-cdf'), analysis.charts.rsrp_cdf);
    globalThis.renderDashboardChart($('ni-sinr-cdf'), analysis.charts.sinr_cdf);
    renderRfTable();
    renderMaps();
    renderSites();
    renderSpectrum();
  };

  let deploymentController = null;
  const loadDeployment = async () => {
    deploymentController?.abort();
    const controller = new AbortController();
    deploymentController = controller;
    const group = $('ni-deployment-group').value;
    const host = $('ni-deployment');
    const note = $('ni-deployment-status');
    if (!(config.inventories || []).length) {
      host.innerHTML = '<p class="ni-pending-box"><strong>Pending input.</strong> Upload the Vodafone or Three cell inventories as Vendor mapping datasets in Workspace to analyse NNS, eMOCN scenarios, host networks and RAN vendors.</p>';
      $('ni-inventory-totals').replaceChildren();
      return;
    }
    note.textContent = 'Loading the cell inventories…';
    const timeout = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(`/api/network-insights/deployment?group=${encodeURIComponent(group)}`, {signal: controller.signal});
      const payload = await response.json();
      if (deploymentController !== controller) return;
      if (!response.ok) throw new Error(payload.detail || 'Unable to load the cell inventories.');
      host.innerHTML = payload.inventories.map(inventory => {
        const maximum = inventory.rows.reduce((maximum, row) => Math.max(maximum, row.sites), 1);
        const available = inventory.available_groups.includes(group);
        return `<section class="ni-inventory"><h3>${escapeHtml(inventory.operator)} <span>${escapeHtml(inventory.file_name)}</span></h3>
          ${available ? '' : `<p class="form-note">This inventory has no ${escapeHtml(payload.group_label)} column; totals are shown instead.</p>`}
          <table class="ni-table"><thead><tr><th>${escapeHtml(available ? payload.group_label : 'Inventory')}</th><th>Sites</th><th>Cells</th><th></th></tr></thead><tbody>${inventory.rows.map(row => `<tr>
            <td>${escapeHtml(row.group)}</td><td class="num">${integer(row.sites)}</td><td class="num">${integer(row.cells)}</td>
            <td><span class="ni-share"><span style="width:${row.sites / maximum * 100}%"></span></span></td></tr>`).join('')}</tbody></table></section>`;
      }).join('');
      $('ni-inventory-totals').innerHTML = payload.inventories.filter(inventory => inventory.totals).map(inventory =>
        `<article class="ni-inventory-total"><span>${escapeHtml(inventory.operator)} inventory</span><strong>${integer(inventory.totals.sites)}</strong><small>sites · ${integer(inventory.totals.cells)} cells</small></article>`).join('');
      note.textContent = 'Sites and cells counted from the uploaded cell inventories (distinct site and cell identifiers).';
    } catch (error) {
      if (deploymentController !== controller) return;
      note.textContent = error.name === 'AbortError'
        ? 'Loading the inventories timed out. Change the grouping or try again.' : error.message;
    } finally {
      clearTimeout(timeout);
    }
  };

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

  $('ni-technology').onchange = syncTechnologyGrouping;
  $('ni-nr-mode').onchange = () => { renderDatasets(); scheduleFilterOptions(); };
  $('ni-datasets').addEventListener('change', scheduleFilterOptions);
  // Keep the map Operator across analyses when it is still part of the selection.
  $('ni-analyse').onclick = () => { void analyse($('ni-map-operator').value || savedSelection.map_group || ''); };
  $('ni-map-operator').onchange = () => { void analyse($('ni-map-operator').value || savedSelection.map_group || ''); };
  $('ni-map-reset').onclick = () => {
    for (const kind of ['coverage', 'interference']) {
      if (!mapPayloads[kind]) continue;
      globalThis.setDashboardChartZoom?.($(`ni-${kind}-map`), 1);
      globalThis.renderDashboardChart($(`ni-${kind}-map`), mapPayloads[kind]);
    }
    if (analysis) $('ni-map-note').textContent = `${analysis.maps.operator} · whole area.`;
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('.ni-zoom');
    if (button) zoomMap(button.dataset.kind, Number(button.dataset.latitude), Number(button.dataset.longitude));
  });
  $('ni-deployment-group').onchange = () => { void loadDeployment(); };
  renderDatasets();
  void loadFilterOptions();
  void loadDeployment();
})();
