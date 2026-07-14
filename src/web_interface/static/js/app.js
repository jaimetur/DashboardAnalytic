function formatAxisValue(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 100) return numeric.toFixed(0);
  if (Math.abs(numeric) >= 10) return numeric.toFixed(1).replace(/\.0$/, '');
  return numeric.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

function limitSeriesCollectionByX(seriesCollection, xMaxOverride) {
  if (!Number.isFinite(Number(xMaxOverride))) return seriesCollection;
  return seriesCollection
    .map((item) => {
      const filteredLabels = [];
      const filteredSeries = [];
      (item.labels || []).forEach((label, index) => {
        if (Number(label) <= Number(xMaxOverride)) {
          filteredLabels.push(label);
          filteredSeries.push((item.series || [])[index]);
        }
      });
      return {...item, labels: filteredLabels, series: filteredSeries};
    })
    .filter((item) => item.labels.length > 0 && item.series.length > 0);
}

function drawLineChart(svg, labels, series, width, height, padding, axisLabels = {}, xMaxOverride = null, xMinOverride = null) {
  const palette = ['#0b7a75', '#dd653e', '#245a96', '#b84d3a', '#6d46a8', '#228a5d', '#c78b1d', '#4d6a88'];
  const rawSeriesCollection = Array.isArray(series) && series.length > 0 && typeof series[0] === 'object' && Array.isArray(series[0].series)
    ? series
    : [{name: 'CDF', labels, series}];
  const seriesCollection = limitSeriesCollectionByX(rawSeriesCollection, xMaxOverride);
  if (seriesCollection.length === 0) {
    svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#526371">No chart data available</text>';
    return;
  }
  const flatLabels = seriesCollection.flatMap((item) => item.labels || []);
  const flatSeries = seriesCollection.flatMap((item) => item.series || []);
  const dataMinX = Math.min(...flatLabels);
  const dataMaxX = Math.max(...flatLabels);
  const minX = Number.isFinite(Number(xMinOverride)) ? Number(xMinOverride) : dataMinX;
  const maxX = Number.isFinite(Number(xMaxOverride)) ? Number(xMaxOverride) : dataMaxX;
  const maxY = Math.max(...flatSeries, 1);
  const legendHeight = seriesCollection.length > 1 ? 28 : 0;
  const xAxisLabel = String(axisLabels.x || 'Metric value');
  const yAxisLabel = String(axisLabels.y || 'Cumulative probability');
  const leftPadding = padding + 26;
  const rightPadding = padding;
  const bottomPadding = padding + 30;
  const innerTop = padding + legendHeight;
  const innerWidth = width - leftPadding - rightPadding;
  const innerHeight = height - bottomPadding - innerTop;
  const domainMinX = Math.min(minX, maxX);
  const domainMaxX = Math.max(minX, maxX);
  const scaleX = (value) => leftPadding + ((value - domainMinX) / ((domainMaxX - domainMinX) || 1)) * innerWidth;
  const scaleY = (value) => height - bottomPadding - (value / maxY) * innerHeight;
  const xTicks = [domainMinX, (domainMinX + domainMaxX) / 2, domainMaxX];
  const yTicks = [0, 0.5, 1.0];
  const xTickLabels = xTicks.map((value) => `
    <line x1="${scaleX(value)}" y1="${height - bottomPadding}" x2="${scaleX(value)}" y2="${height - bottomPadding + 6}" stroke="#9ab0bc" />
    <text x="${scaleX(value)}" y="${height - bottomPadding + 18}" text-anchor="middle" fill="#526371" font-size="11">${formatAxisValue(value)}</text>
  `).join('');
  const yTickLabels = yTicks.map((value) => `
    <line x1="${leftPadding - 6}" y1="${scaleY(value)}" x2="${leftPadding}" y2="${scaleY(value)}" stroke="#9ab0bc" />
    <text x="${leftPadding - 10}" y="${scaleY(value) + 4}" text-anchor="end" fill="#526371" font-size="11">${formatAxisValue(value)}</text>
  `).join('');
  const lines = seriesCollection.map((item, index) => {
    const color = palette[index % palette.length];
    const points = (item.labels || []).map((label, pointIndex) => `${scaleX(label)},${scaleY((item.series || [])[pointIndex])}`).join(' ');
    return `<polyline fill="none" stroke="${color}" stroke-width="3" points="${points}" />`;
  }).join('');
  const legend = seriesCollection.length > 1
    ? seriesCollection.map((item, index) => {
        const color = palette[index % palette.length];
        const x = padding + (index % 3) * 170;
        const y = 18 + Math.floor(index / 3) * 18;
        return `
          <circle cx="${x}" cy="${y}" r="5" fill="${color}"></circle>
          <text x="${x + 10}" y="${y + 4}" fill="#526371" font-size="11">${String(item.name).slice(0, 20)}</text>
        `;
      }).join('')
    : `<text x="${padding}" y="18" fill="#526371">CDF</text>`;
  svg.innerHTML = `
    <line x1="${leftPadding}" y1="${height - bottomPadding}" x2="${width - rightPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    <line x1="${leftPadding}" y1="${innerTop}" x2="${leftPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    ${xTickLabels}
    ${yTickLabels}
    ${legend}
    ${lines}
    <text x="${leftPadding + innerWidth / 2}" y="${height - 4}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600">${xAxisLabel}</text>
    <text x="16" y="${innerTop + innerHeight / 2}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600" transform="rotate(-90 16 ${innerTop + innerHeight / 2})">${yAxisLabel}</text>
  `;
}

function drawBarChart(svg, labels, series, width, height, padding, axisLabels = {}) {
  const numericSeries = series.map((value) => Number(value)).filter((value) => Number.isFinite(value));
  const maxValue = numericSeries.length > 0 ? Math.max(...numericSeries) : 1;
  const yAxisLabel = String(axisLabels.y || 'Mean metric');
  const leftPadding = padding + 26;
  const bottomPadding = padding + 18;
  const topPadding = padding;
  const innerWidth = width - leftPadding - padding;
  const innerHeight = height - topPadding - bottomPadding;
  const barWidth = innerWidth / labels.length;
  const bars = labels.map((label, index) => {
    const value = series[index];
    const scaledHeight = ((Number(value) || 0) / (maxValue || 1)) * innerHeight;
    const x = leftPadding + index * barWidth + 8;
    const y = height - bottomPadding - scaledHeight;
    const textX = x + Math.max(barWidth - 16, 24) / 2;
    const valueLabel = Number.isFinite(Number(value)) ? Number(value).toFixed(Math.abs(Number(value)) >= 100 ? 0 : 2).replace(/\.00$/, '') : String(value);
    const valueY = scaledHeight > 28 ? y + 18 : Math.max(y - 8, topPadding + 12);
    const valueFill = scaledHeight > 28 ? 'rgba(255,255,255,0.96)' : '#334550';
    return `
      <rect x="${x}" y="${y}" width="${Math.max(barWidth - 16, 24)}" height="${scaledHeight}" rx="10" fill="#dd653e"></rect>
      <text x="${textX}" y="${valueY}" text-anchor="middle" fill="${valueFill}" font-size="11" font-weight="700">${valueLabel}</text>
      <text x="${textX}" y="${height - 10}" text-anchor="middle" fill="#526371" font-size="11">${String(label).slice(0, 12)}</text>
    `;
  }).join('');
  svg.innerHTML = `
    <line x1="${leftPadding}" y1="${height - bottomPadding}" x2="${width - padding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    <line x1="${leftPadding}" y1="${topPadding}" x2="${leftPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    ${bars}
    <text x="16" y="${topPadding + innerHeight / 2}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600" transform="rotate(-90 16 ${topPadding + innerHeight / 2})">${yAxisLabel}</text>
  `;
}

function drawChart(container) {
  const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[],"type":"line"}');
  const svg = container.querySelector('.chart-svg');
  const labels = payload.labels || [];
  const series = payload.series || [];
  const seriesCollection = payload.series_collection || [];
  const hasLineData = (labels.length > 0 && series.length > 0) || seriesCollection.length > 0;
  if (!svg || (payload.type === 'line' ? !hasLineData : (labels.length === 0 || series.length === 0))) {
    if (svg) {
      svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#526371">No chart data available</text>';
    }
    return;
  }
  const width = 600;
  const isCdfChart = container.dataset.chartKind === 'cdf';
  const height = isCdfChart ? 280 : Math.max(Math.round(svg.getBoundingClientRect().height || 280), 280);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const padding = 34;
  if (payload.type === 'bar') {
    drawBarChart(svg, labels, series, width, height, padding, {y: payload.y_axis_label});
    return;
  }
  const activeXMax = Number(container.dataset.cdfXMax || payload.x_view_max_default || payload.x_max);
  drawLineChart(
    svg,
    labels,
    seriesCollection.length > 0 ? seriesCollection : series,
    width,
    height,
    padding,
    {x: payload.x_axis_label, y: payload.y_axis_label},
    activeXMax,
    0,
  );
}

function setupCdfRangeControls() {
  document.querySelectorAll('.chart-card[data-chart-kind="cdf"]').forEach((container) => {
    const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[],"type":"line"}');
    const control = container.querySelector('[data-cdf-range-control]');
    const slider = container.querySelector('[data-cdf-range-slider]');
    const valueNode = container.querySelector('[data-cdf-range-value]');
    const xMin = Number(payload.x_min);
    const xMax = Number(payload.x_max);
    const defaultXMax = Number(payload.x_view_max_default);
    const recommendedXMax = Number(payload.x_view_max_recommended);

    if (!control || !slider || !Number.isFinite(xMin) || !Number.isFinite(xMax) || xMax <= xMin) {
      if (control) control.hidden = true;
      return;
    }

    slider.min = String(xMin);
    slider.max = String(xMax);
    slider.step = String(Math.max((xMax - xMin) / 400, 0.0001));
    slider.value = String(Number.isFinite(defaultXMax) ? defaultXMax : xMax);
    container.dataset.cdfXMax = slider.value;

    const updateRangeUi = () => {
      const currentValue = Number(slider.value);
      container.dataset.cdfXMax = String(currentValue);
      if (valueNode) {
        valueNode.textContent = `${formatAxisValue(xMin)} -> ${formatAxisValue(currentValue)}`;
      }
      drawChart(container);
    };

    control.hidden = false;
    slider.addEventListener('input', updateRangeUi);
    slider.addEventListener('change', updateRangeUi);
    updateRangeUi();
  });
}

document.querySelectorAll('[data-chart]').forEach(drawChart);
setupCdfRangeControls();

document.querySelectorAll('.collapsible-panel').forEach((panel) => {
  const chip = panel.querySelector('.collapse-chip');
  const updateChip = () => {
    if (!chip) return;
    chip.textContent = panel.open ? 'Collapse' : 'Expand';
  };
  updateChip();
  panel.addEventListener('toggle', updateChip);
});

const loadingOverlay = document.getElementById('loading-overlay');
const loadingTitle = document.getElementById('loading-title');
const loadingCopy = document.getElementById('loading-copy');
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmTitle = document.getElementById('confirm-title');
const confirmCopy = document.getElementById('confirm-copy');
const confirmAccept = document.getElementById('confirm-accept');
const confirmCancel = document.getElementById('confirm-cancel');
const filePickerInput = document.querySelector('[data-file-picker-input]');
const filePickerText = document.querySelector('[data-file-picker-text]');
const inputKindSelect = document.querySelector('[data-input-kind-select]');
const datasetSelect = document.querySelector('[data-dataset-select]');
const logTypeFilter = document.querySelector('[data-log-type-filter]');
const persistencePathnames = new Set(['/dashboard', '/admin']);
const dashboardStateKey = 'dashboard-analytic:/dashboard:last-query';
const dashboardStateKeyPrefix = 'dashboard-analytic:/dashboard:last-query:dataset:';
const activeDatasetStateKey = 'dashboard-analytic:active-dataset';
let hasPendingLocationRestore = false;

function hasMeaningfulDashboardState(params) {
  if (!params) return false;
  for (const [key, value] of params.entries()) {
    if (key === 'dataset_id' || key === 'input_kind' || key === 'load') continue;
    if ((key === 'aggregation' || key === 'cdf_grouping') && String(value || '').trim().toLowerCase() === 'all') continue;
    if (String(value || '').trim()) {
      return true;
    }
  }
  return false;
}

function sanitizeDashboardState(params) {
  const source = params instanceof URLSearchParams ? params : new URLSearchParams(params || '');
  const sanitized = new URLSearchParams(source.toString());
  sanitized.delete('aggregation_overrides');
  sanitized.delete('cdf_overrides');
  return sanitized;
}

function buildDashboardStateKey(datasetId) {
  const normalizedDatasetId = String(datasetId || '').trim();
  return normalizedDatasetId ? `${dashboardStateKeyPrefix}${normalizedDatasetId}` : dashboardStateKey;
}

function getDashboardStateKeyForParams(params) {
  return buildDashboardStateKey(params?.get?.('dataset_id'));
}

function getPersistedDashboardQuery(params) {
  const stateKey = getDashboardStateKeyForParams(params || new URLSearchParams());
  let persistedQuery = window.localStorage.getItem(stateKey);
  if (!persistedQuery && stateKey !== dashboardStateKey) {
    persistedQuery = window.localStorage.getItem(dashboardStateKey);
  }
  return persistedQuery;
}

function persistDashboardState(params) {
  if (!hasMeaningfulDashboardState(params)) return;
  try {
    const sanitized = sanitizeDashboardState(params);
    const serialized = sanitized.toString();
    window.localStorage.setItem(getDashboardStateKeyForParams(params), serialized);
    window.localStorage.setItem(dashboardStateKey, serialized);
  } catch (_error) {
    // Ignore storage failures.
  }
}

function persistActiveDatasetState(params) {
  const datasetId = String(params.get('dataset_id') || '').trim();
  if (!datasetId) return;
  const inputKind = String(params.get('input_kind') || '').trim();
  try {
    window.localStorage.setItem(activeDatasetStateKey, JSON.stringify({
      dataset_id: datasetId,
      input_kind: inputKind,
    }));
  } catch (_error) {
    // Ignore storage failures.
  }
}

function buildRestoredDashboardUrl(currentParams, persistedDashboardQuery) {
  const persistedParams = sanitizeDashboardState(new URLSearchParams(persistedDashboardQuery || ''));
  const merged = new URLSearchParams(persistedParams.toString());
  const currentDatasetId = String(currentParams.get('dataset_id') || '').trim();
  const currentInputKind = String(currentParams.get('input_kind') || '').trim();
  if (currentDatasetId) {
    merged.set('dataset_id', currentDatasetId);
  }
  if (currentInputKind) {
    merged.set('input_kind', currentInputKind);
  } else {
    merged.delete('input_kind');
  }
  const query = merged.toString();
  return query ? `/dashboard?${query}` : '/dashboard';
}

function restoreActiveDatasetState() {
  try {
    const rawValue = window.localStorage.getItem(activeDatasetStateKey);
    if (!rawValue) return null;
    const parsed = JSON.parse(rawValue);
    if (!parsed || !parsed.dataset_id) return null;
    return {
      dataset_id: String(parsed.dataset_id),
      input_kind: String(parsed.input_kind || ''),
    };
  } catch (_error) {
    return null;
  }
}

function replaceLocation(url) {
  hasPendingLocationRestore = true;
  window.location.replace(url);
}

function buildDashboardParamsFromForm(form) {
  const params = new URLSearchParams();
  const formData = new FormData(form);
  for (const [key, value] of formData.entries()) {
    if (value == null) continue;
    const normalized = String(value);
    if (!normalized.trim()) continue;
    params.append(key, normalized);
  }
  form.querySelectorAll('select[multiple][name]').forEach((select) => {
    const enabledOptions = Array.from(select.options).filter((option) => !option.disabled);
    const selectedCount = enabledOptions.filter((option) => option.selected).length;
    if (enabledOptions.length > 0 && selectedCount === 0) {
      params.append('__empty_filter', select.name);
    }
  });
  document.querySelectorAll(`[form="${form.id}"][name]`).forEach((control) => {
    if (form.contains(control)) return;
    const tagName = String(control.tagName || '').toLowerCase();
    if (tagName !== 'select' && tagName !== 'input' && tagName !== 'textarea') return;
    if (control.disabled) return;
    if (tagName === 'select' && control.multiple) {
      params.delete(control.name);
      const enabledOptions = Array.from(control.options).filter((option) => !option.disabled);
      const selectedOptions = enabledOptions.filter((option) => option.selected);
      selectedOptions.forEach((option) => params.append(control.name, String(option.value)));
      if (enabledOptions.length > 0 && selectedOptions.length === 0) {
        params.append('__empty_filter', control.name);
      }
      return;
    }
    if ((tagName === 'input') && String(control.type || '').toLowerCase() === 'checkbox') {
      params.delete(control.name);
      if (control.checked) params.append(control.name, String(control.value || 'on'));
      return;
    }
    params.delete(control.name);
    const value = String(control.value || '').trim();
    if (value) {
      params.append(control.name, value);
    }
  });
  return params;
}

function syncDashboardHiddenControl(name, value) {
  const form = document.getElementById('dashboard-filters-form');
  if (!form) return;
  const control = form.querySelector(`input[type="hidden"][name="${name}"]`);
  if (control) {
    control.value = String(value || 'all').trim() || 'all';
  }
}

function parseAggregationOverrides(rawValue) {
  const overrides = new Map();
  String(rawValue || '')
    .split(';')
    .map((entry) => entry.trim())
    .filter(Boolean)
    .forEach((entry) => {
      const separator = entry.indexOf('=');
      if (separator <= 0) return;
      const metric = entry.slice(0, separator).trim();
      const aggregation = entry.slice(separator + 1).trim();
      if (metric && aggregation) {
        overrides.set(metric, aggregation);
      }
    });
  return overrides;
}

function formatAggregationOverrides(overrides) {
  return Array.from(overrides.entries())
    .filter(([metric, aggregation]) => metric && aggregation)
    .map(([metric, aggregation]) => `${metric}=${aggregation}`)
    .join(';');
}

function canPersistControl(control) {
  if (!control || !persistencePathnames.has(window.location.pathname)) return false;
  if (!control.name || control.disabled) return false;
  const tagName = String(control.tagName || '').toLowerCase();
  const type = String(control.type || '').toLowerCase();
  if (tagName === 'input' && ['hidden', 'file', 'submit', 'button', 'image', 'reset'].includes(type)) return false;
  return ['input', 'select', 'textarea'].includes(tagName);
}

function buildPersistenceKey(control) {
  const explicitForm = control.getAttribute('form');
  const ownerForm = control.form;
  const formKey = explicitForm || ownerForm?.id || ownerForm?.getAttribute('action') || 'standalone';
  return `dashboard-analytic:${window.location.pathname}:${formKey}:${control.name}`;
}

function serializeControlValue(control) {
  if (control.tagName === 'SELECT' && control.multiple) {
    return JSON.stringify(Array.from(control.selectedOptions).map((option) => option.value));
  }
  if (String(control.type || '').toLowerCase() === 'checkbox') {
    return JSON.stringify(Boolean(control.checked));
  }
  if (String(control.type || '').toLowerCase() === 'radio') {
    return JSON.stringify(control.checked ? control.value : null);
  }
  return JSON.stringify(control.value);
}

function restoreControlValue(control, rawValue) {
  let parsedValue;
  try {
    parsedValue = JSON.parse(rawValue);
  } catch (_error) {
    return;
  }

  if (control.tagName === 'SELECT' && control.multiple) {
    const selectedValues = new Set(Array.isArray(parsedValue) ? parsedValue.map(String) : []);
    Array.from(control.options).forEach((option) => {
      option.selected = selectedValues.has(String(option.value));
    });
    return;
  }
  if (String(control.type || '').toLowerCase() === 'checkbox') {
    control.checked = Boolean(parsedValue);
    return;
  }
  if (String(control.type || '').toLowerCase() === 'radio') {
    control.checked = parsedValue !== null && String(control.value) === String(parsedValue);
    return;
  }
  control.value = parsedValue == null ? '' : String(parsedValue);
}

function queryAlreadyControlsValue(control) {
  if (window.location.pathname !== '/dashboard') return false;
  const params = new URLSearchParams(window.location.search);
  if (
    control &&
    (control.name === 'aggregation' || control.name === 'cdf_grouping') &&
    String(params.get(control.name) || '').trim().toLowerCase() === 'all'
  ) {
    return false;
  }
  return params.has(control.name);
}

function getPersistedControlValue(control) {
  if (!canPersistControl(control)) return null;
  const rawValue = window.localStorage.getItem(buildPersistenceKey(control));
  if (rawValue == null) return null;
  try {
    const parsed = JSON.parse(rawValue);
    return parsed == null ? null : String(parsed);
  } catch (_error) {
    return null;
  }
}

function setupPersistentControls() {
  document.querySelectorAll('input[name], select[name], textarea[name]').forEach((control) => {
    if (!canPersistControl(control)) return;
    const key = buildPersistenceKey(control);
    const storedValue = window.localStorage.getItem(key);
    if (storedValue !== null && !queryAlreadyControlsValue(control)) {
      restoreControlValue(control, storedValue);
    }

    const persist = () => {
      try {
        window.localStorage.setItem(key, serializeControlValue(control));
      } catch (_error) {
        // Ignore storage quota / privacy mode failures.
      }
    };

    control.addEventListener('change', persist);
    control.addEventListener('input', persist);
  });
}

function setupPersistentPanelState() {
  document.querySelectorAll('details[data-panel-state-key]').forEach((panel) => {
    const stateKey = `dashboard-analytic:panel:${panel.dataset.panelStateKey}`;
    const storedValue = window.localStorage.getItem(stateKey);
    if (storedValue !== null) {
      panel.open = storedValue === 'open';
    }

    panel.addEventListener('toggle', () => {
      try {
        window.localStorage.setItem(stateKey, panel.open ? 'open' : 'closed');
      } catch (_error) {
        // Ignore storage failures.
      }
    });
  });
}

function setupCustomMultiSelects() {
  document.querySelectorAll('select[multiple]').forEach((select) => {
    if (select.dataset.multiselectReady === '1') return;
    select.dataset.multiselectReady = '1';
    select.classList.add('multiselect-native');

    const shell = document.createElement('div');
    shell.className = 'multiselect-shell';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'multiselect-trigger';
    trigger.setAttribute('aria-expanded', 'false');

    const triggerLabel = document.createElement('span');
    triggerLabel.className = 'multiselect-trigger-label';

    const triggerChip = document.createElement('span');
    triggerChip.className = 'multiselect-trigger-chip';

    trigger.appendChild(triggerLabel);
    trigger.appendChild(triggerChip);

    const menu = document.createElement('div');
    menu.className = 'multiselect-menu';
    menu.hidden = true;

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.className = 'multiselect-action';
    actionButton.textContent = 'Select All / None';
    menu.appendChild(actionButton);

    const syncTrigger = () => {
      const enabledOptions = Array.from(select.options).filter((option) => !option.disabled);
      const selectedOptions = enabledOptions.filter((option) => option.selected).map((option) => option.textContent?.trim()).filter(Boolean);
      const totalEnabled = enabledOptions.length;
      if (totalEnabled === 0) {
        triggerLabel.textContent = 'No values';
      } else if (selectedOptions.length === 0) {
        triggerLabel.textContent = 'No values selected';
      } else if (totalEnabled > 0 && selectedOptions.length === totalEnabled) {
        triggerLabel.textContent = 'All values';
      } else if (selectedOptions.length === 1) {
        triggerLabel.textContent = selectedOptions[0];
      } else {
        triggerLabel.textContent = `${selectedOptions.length}/${totalEnabled} selected`;
      }
      trigger.setAttribute('aria-expanded', String(!menu.hidden));
    };

    const dispatchNativeChange = () => {
      select.dispatchEvent(new Event('change', {bubbles: true}));
      select.dispatchEvent(new Event('input', {bubbles: true}));
      syncTrigger();
    };

    const selectAllOrNone = () => {
      const options = Array.from(select.options).filter((option) => !option.disabled);
      const shouldSelectAll = options.some((option) => !option.selected);
      options.forEach((option) => {
        option.selected = shouldSelectAll;
      });
      Array.from(menu.querySelectorAll('input[type="checkbox"][data-option-value]')).forEach((checkbox) => {
        if (!checkbox.disabled) {
          checkbox.checked = shouldSelectAll;
        }
      });
      dispatchNativeChange();
    };

    actionButton.addEventListener('click', selectAllOrNone);

    Array.from(select.options).forEach((option) => {
      const optionLabel = document.createElement('label');
      optionLabel.className = 'multiselect-option';

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = option.selected;
      checkbox.setAttribute('data-option-value', option.value);
      checkbox.disabled = option.disabled;

      const text = document.createElement('span');
      text.textContent = option.textContent || option.value;

      checkbox.addEventListener('change', () => {
        if (option.disabled) return;
        option.selected = checkbox.checked;
        dispatchNativeChange();
      });

      if (option.disabled) {
        optionLabel.classList.add('is-disabled');
        optionLabel.title = 'This metric is not selectable because the dataset has no numeric values for it.';
      }

      optionLabel.appendChild(checkbox);
      optionLabel.appendChild(text);
      menu.appendChild(optionLabel);
    });

    const syncCheckboxes = () => {
      Array.from(menu.querySelectorAll('input[type="checkbox"][data-option-value]')).forEach((checkbox) => {
        const option = Array.from(select.options).find((item) => item.value === checkbox.getAttribute('data-option-value'));
        if (option) {
          checkbox.checked = option.selected;
        }
      });
      syncTrigger();
    };

    trigger.addEventListener('click', () => {
      menu.hidden = !menu.hidden;
      syncTrigger();
    });

    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) {
        menu.hidden = true;
        syncTrigger();
      }
    });

    select.addEventListener('change', syncCheckboxes);
    select.after(shell);
    shell.appendChild(trigger);
    shell.appendChild(menu);
    syncCheckboxes();
  });
}

function hideLoadingOverlay() {
  if (!loadingOverlay) return;
  loadingOverlay.hidden = true;
  document.body.classList.remove('loading-active');
}

function showLoadingOverlay(label) {
  if (!loadingOverlay) return;
  loadingTitle.textContent = label || 'Processing request';
  loadingCopy.textContent = 'Please wait while the workspace processes the selected dataset or updates the dashboard.';
  loadingOverlay.hidden = false;
  document.body.classList.add('loading-active');
}

hideLoadingOverlay();
window.addEventListener('pageshow', hideLoadingOverlay);

function resolveDownloadFilename(response, fallbackName) {
  const disposition = response.headers.get('content-disposition') || '';
  const utf8Match = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (_error) {
      return utf8Match[1];
    }
  }
  const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
  return match ? match[1] : fallbackName;
}

async function submitDownloadForm(form) {
  showLoadingOverlay(form.dataset.loadingLabel);
  try {
    const response = await fetch(form.action, {
      method: String(form.method || 'post').toUpperCase(),
      body: new FormData(form),
      credentials: 'same-origin',
    });
    if (!response.ok) {
      hideLoadingOverlay();
      alert(`Download failed with status ${response.status}.`);
      return;
    }
    const blob = await response.blob();
    const fallbackName = form.action.includes('/powerpoint') ? 'report.pptx' : 'report.docx';
    const filename = resolveDownloadFilename(response, fallbackName);
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
  } catch (_error) {
    alert('Download failed. Please try again.');
  } finally {
    hideLoadingOverlay();
  }
}

if (window.location.pathname === '/dashboard') {
  const params = new URLSearchParams(window.location.search);
  const persistedDashboardQuery = getPersistedDashboardQuery(params);
  if (params.get('dataset_id')) {
    persistActiveDatasetState(params);
  }
  if (hasMeaningfulDashboardState(params)) {
    persistDashboardState(params);
  } else if (persistedDashboardQuery) {
    replaceLocation(buildRestoredDashboardUrl(params, persistedDashboardQuery));
  }
}

if (window.location.pathname === '/workspace') {
  const params = new URLSearchParams(window.location.search);
  if (params.get('dataset_id')) {
    persistActiveDatasetState(params);
  } else {
    const activeDataset = restoreActiveDatasetState();
    if (activeDataset?.dataset_id) {
      params.set('dataset_id', activeDataset.dataset_id);
      if (activeDataset.input_kind) {
        params.set('input_kind', activeDataset.input_kind);
      }
      replaceLocation(`/workspace?${params.toString()}`);
    }
  }
}

setupPersistentControls();
setupPersistentPanelState();
setupCustomMultiSelects();

function maybeSyncPersistedGlobalDashboardSelectors() {
  if (window.location.pathname !== '/dashboard' || hasPendingLocationRestore) return;
  const aggregationSelect = document.querySelector('[data-global-aggregation-select]');
  const cdfSelect = document.querySelector('[data-global-cdf-grouping-select]');
  if (!aggregationSelect && !cdfSelect) return;

  const params = new URLSearchParams(window.location.search);
  let shouldReplace = false;

  const persistedAggregation = aggregationSelect ? getPersistedControlValue(aggregationSelect) : null;
  if (
    aggregationSelect &&
    persistedAggregation &&
    persistedAggregation !== 'all' &&
    String(params.get('aggregation') || '').trim().toLowerCase() === 'all'
  ) {
    params.set('aggregation', persistedAggregation);
    shouldReplace = true;
  }

  const persistedCdfGrouping = cdfSelect ? getPersistedControlValue(cdfSelect) : null;
  if (
    cdfSelect &&
    persistedCdfGrouping &&
    persistedCdfGrouping !== 'all' &&
    String(params.get('cdf_grouping') || '').trim().toLowerCase() === 'all'
  ) {
    params.set('cdf_grouping', persistedCdfGrouping);
    shouldReplace = true;
  }

  if (!shouldReplace) return;
  if (!params.get('load')) {
    params.set('load', '1');
  }
  replaceLocation(`/dashboard?${params.toString()}`);
}

maybeSyncPersistedGlobalDashboardSelectors();

document.querySelectorAll('form[data-loading-label]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.downloadForm === '1') {
      event.preventDefault();
      submitDownloadForm(form);
      return;
    }
    if (window.location.pathname === '/dashboard' && form.id === 'dashboard-filters-form') {
      event.preventDefault();
      const globalCdfSelect = document.querySelector('[data-global-cdf-grouping-select]');
      const globalAggregationSelect = document.querySelector('[data-global-aggregation-select]');
      syncDashboardHiddenControl('cdf_grouping', globalCdfSelect?.value || 'all');
      syncDashboardHiddenControl('aggregation', globalAggregationSelect?.value || 'all');
      const params = buildDashboardParamsFromForm(form);
      params.set('load', '1');
      params.delete('cdf_overrides');
      persistDashboardState(params);
      persistActiveDatasetState(params);
      showLoadingOverlay(form.dataset.loadingLabel);
      window.location.search = params.toString();
      return;
    }
    showLoadingOverlay(form.dataset.loadingLabel);
  });
});

function showConfirmDialog(message, options = {}) {
  if (!confirmOverlay || !confirmTitle || !confirmCopy || !confirmAccept || !confirmCancel) {
    return Promise.resolve(window.confirm(message || 'Are you sure?'));
  }

  confirmTitle.textContent = options.title || 'Confirm action';
  confirmCopy.textContent = message || options.copy || 'Are you sure you want to continue?';
  confirmAccept.textContent = options.confirmLabel || 'Confirm';
  confirmOverlay.hidden = false;
  document.body.classList.add('loading-active');

  return new Promise((resolve) => {
    const close = (accepted) => {
      confirmOverlay.hidden = true;
      document.body.classList.remove('loading-active');
      confirmAccept.removeEventListener('click', handleAccept);
      confirmCancel.removeEventListener('click', handleCancel);
      confirmOverlay.removeEventListener('click', handleBackdrop);
      window.removeEventListener('keydown', handleKeydown);
      resolve(accepted);
    };

    const handleAccept = () => close(true);
    const handleCancel = () => close(false);
    const handleBackdrop = (event) => {
      if (event.target === confirmOverlay) {
        close(false);
      }
    };
    const handleKeydown = (event) => {
      if (event.key === 'Escape') {
        close(false);
      }
    };

    confirmAccept.addEventListener('click', handleAccept);
    confirmCancel.addEventListener('click', handleCancel);
    confirmOverlay.addEventListener('click', handleBackdrop);
    window.addEventListener('keydown', handleKeydown);
    confirmAccept.focus();
  });
}

document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const accepted = await showConfirmDialog(form.dataset.confirm, {
      title: form.dataset.confirmTitle || 'Confirm action',
      confirmLabel: form.dataset.confirmLabel || 'Confirm',
    });
    if (accepted) {
      form.submit();
    }
  });
});

if (filePickerInput && filePickerText) {
  filePickerInput.addEventListener('change', () => {
    const files = Array.from(filePickerInput.files || []);
    if (files.length === 0) {
      filePickerText.textContent = 'No files selected';
      return;
    }
    if (files.length === 1) {
      filePickerText.textContent = files[0].name;
      return;
    }
    filePickerText.textContent = `${files.length} files selected`;
  });
}

if (inputKindSelect && datasetSelect) {
  const persistControlValue = (control, value) => {
    try {
      window.localStorage.setItem(buildPersistenceKey(control), JSON.stringify(value));
    } catch (_error) {
      // Ignore storage failures.
    }
  };

  const syncDatasetOptions = () => {
    const selectedKind = String(inputKindSelect.value || '');
    const options = Array.from(datasetSelect.options);
    let firstVisibleValue = '';

    options.forEach((option) => {
      const optionKind = String(option.dataset.datasetKind || 'generic');
      const visible = !selectedKind || optionKind === selectedKind;
      option.hidden = !visible;
      option.disabled = !visible;
      if (visible && !firstVisibleValue) {
        firstVisibleValue = option.value;
      }
    });

    const selectedOption = datasetSelect.selectedOptions[0];
    if (!selectedOption || selectedOption.hidden || selectedOption.disabled) {
      datasetSelect.value = firstVisibleValue;
    }
  };

  inputKindSelect.addEventListener('change', syncDatasetOptions);
  syncDatasetOptions();

  const persistActiveDatasetContext = () => {
    const params = new URLSearchParams(window.location.search);
    const currentDatasetId = params.get('dataset_id') || datasetSelect.value;
    if (!currentDatasetId) return;

    const matchingOption = Array.from(datasetSelect.options).find((option) => String(option.value) === String(currentDatasetId));
    if (!matchingOption) return;

    persistControlValue(datasetSelect, String(currentDatasetId));
    const datasetKind = String(matchingOption.dataset.datasetKind || '');
    if (datasetKind) {
      persistControlValue(inputKindSelect, datasetKind);
    }
    const datasetParams = new URLSearchParams();
    datasetParams.set('dataset_id', String(currentDatasetId));
    if (datasetKind) {
      datasetParams.set('input_kind', datasetKind);
    }
    persistActiveDatasetState(datasetParams);
  };

  const maybeRestoreLastDataset = () => {
    if (window.location.pathname !== '/dashboard' || hasPendingLocationRestore) return;
    const params = new URLSearchParams(window.location.search);
    if (params.has('dataset_id')) {
      persistActiveDatasetContext();
      return;
    }
    const persistedDatasetId = window.localStorage.getItem(buildPersistenceKey(datasetSelect));
    if (!persistedDatasetId) return;

    let restoredValue;
    try {
      restoredValue = JSON.parse(persistedDatasetId);
    } catch (_error) {
      return;
    }
    if (!restoredValue) return;

    const matchingOption = Array.from(datasetSelect.options).find((option) => String(option.value) === String(restoredValue));
    if (!matchingOption) return;

    params.set('dataset_id', String(restoredValue));
    const matchingKind = String(matchingOption.dataset.datasetKind || '');
    if (matchingKind) {
      params.set('input_kind', matchingKind);
    } else if (inputKindSelect.value) {
      params.set('input_kind', String(inputKindSelect.value));
    }
    replaceLocation(`/dashboard?${params.toString()}`);
  };

  persistActiveDatasetContext();
  maybeRestoreLastDataset();
}

if (logTypeFilter) {
  const syncLogRows = () => {
    const selectedType = String(logTypeFilter.value || 'Error');
    document.querySelectorAll('[data-log-row]').forEach((row) => {
      const rowType = String(row.getAttribute('data-log-type') || 'Info');
      row.hidden = selectedType !== 'all' && rowType !== selectedType;
    });
  };

  logTypeFilter.addEventListener('change', syncLogRows);
  syncLogRows();
}

document.querySelectorAll('[data-chart-aggregation-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const metric = String(select.dataset.metric || '').trim();
    if (!metric) return;
    const selectedAggregation = String(select.value || 'all').trim();
    const globalAggregation = String(select.dataset.globalAggregation || 'all').trim();
    const overrides = parseAggregationOverrides(select.dataset.currentOverrides || '');
    if (!selectedAggregation || selectedAggregation === 'all' || selectedAggregation === globalAggregation) {
      overrides.delete(metric);
    } else {
      overrides.set(metric, selectedAggregation);
    }

    const params = new URLSearchParams(window.location.search);
    const serialized = formatAggregationOverrides(overrides);
    if (serialized) {
      params.set('aggregation_overrides', serialized);
    } else {
      params.delete('aggregation_overrides');
    }
    params.set('load', '1');
    persistDashboardState(params);
    persistActiveDatasetState(params);
    showLoadingOverlay(`Updating ${metric} comparison`);
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-summary-control]').forEach((node) => {
  ['click', 'mousedown', 'mouseup', 'keydown'].forEach((eventName) => {
    node.addEventListener(eventName, (event) => {
      event.stopPropagation();
    });
  });
});

document.querySelectorAll('[data-global-aggregation-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.form || document.getElementById('dashboard-filters-form');
    if (!form) return;
    syncDashboardHiddenControl('aggregation', select.value || 'all');
    const params = buildDashboardParamsFromForm(form);
    params.set('aggregation', String(select.value || 'all'));
    params.set('load', '1');
    params.delete('aggregation_overrides');
    persistDashboardState(params);
    showLoadingOverlay('Updating all chart aggregations');
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-global-cdf-grouping-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.form || document.getElementById('dashboard-filters-form');
    if (!form) return;
    syncDashboardHiddenControl('cdf_grouping', select.value || 'all');
    const params = buildDashboardParamsFromForm(form);
    params.set('cdf_grouping', String(select.value || 'all'));
    params.set('load', '1');
    params.delete('cdf_overrides');
    persistDashboardState(params);
    showLoadingOverlay('Updating all CDF comparisons');
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-chart-cdf-grouping-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const metric = String(select.dataset.metric || '').trim();
    if (!metric) return;
    const selectedGrouping = String(select.value || 'all').trim();
    const globalGrouping = String(select.dataset.globalCdfGrouping || 'all').trim();
    const overrides = parseAggregationOverrides(select.dataset.currentOverrides || '');
    if (!selectedGrouping || selectedGrouping === 'all' || selectedGrouping === globalGrouping) {
      overrides.delete(metric);
    } else {
      overrides.set(metric, selectedGrouping);
    }
    const params = new URLSearchParams(window.location.search);
    const serialized = formatAggregationOverrides(overrides);
    if (serialized) {
      params.set('cdf_overrides', serialized);
    } else {
      params.delete('cdf_overrides');
    }
    params.set('load', '1');
    persistDashboardState(params);
    persistActiveDatasetState(params);
    showLoadingOverlay(`Updating ${metric} CDF comparison`);
    window.location.search = params.toString();
  });
});

const queueNode = document.querySelector('[data-queue-status-url]');
if (queueNode) {
  const url = queueNode.dataset.queueStatusUrl || '';
  const delay = Number(queueNode.dataset.queuePollMs || '0');
  const selectedDatasetField = document.querySelector('input[name="dataset_id"], select[name="dataset_id"]');
  const waitingPanel = document.querySelector('.queue-waiting-copy');

  const updateQueueRow = (dataset) => {
    const row = document.querySelector(`[data-dataset-row][data-dataset-id="${dataset.id}"]`);
    if (!row) return;
    const kind = row.querySelector('[data-queue-kind]');
    const rows = row.querySelector('[data-queue-rows]');
    const size = row.querySelector('[data-queue-size]');
    const statusPill = row.querySelector('[data-queue-status-pill]');
    const progressBar = row.querySelector('[data-queue-progress-bar]');
    const progressLabel = row.querySelector('[data-queue-progress-label]');
    const updated = row.querySelector('[data-queue-updated]');
    const actions = row.querySelector('.queue-actions');
    let errorNode = row.querySelector('[data-queue-error]');

    if (kind) kind.textContent = dataset.input_kind_label || 'Other';
    if (rows) rows.textContent = String(dataset.row_count || 0);
    if (size) size.textContent = dataset.size_mb_label || '0.00 MB';
    if (statusPill) {
      statusPill.textContent = dataset.status_label || dataset.status || 'Queued';
      statusPill.className = `queue-status-pill queue-status-${dataset.status}`;
    }
    if (progressBar) {
      progressBar.style.width = `${dataset.progress || 0}%`;
      progressBar.className = `progress-bar status-${dataset.status}`;
    }
    if (progressLabel) progressLabel.textContent = `${dataset.progress || 0}%`;
    if (updated) updated.textContent = dataset.updated_at || dataset.uploaded_at || '';
    if (dataset.last_error && (dataset.status === 'failed' || dataset.status === 'stopped')) {
      if (!errorNode && progressLabel && progressLabel.parentElement) {
        errorNode = document.createElement('p');
        errorNode.className = 'dataset-error';
        errorNode.setAttribute('data-queue-error', '');
        progressLabel.parentElement.appendChild(errorNode);
      }
      if (errorNode) {
        errorNode.textContent = dataset.last_error;
      }
    } else if (errorNode) {
      errorNode.remove();
    }
    if (actions) {
      const openParams = new URLSearchParams();
      openParams.set('dataset_id', String(dataset.id));
      if (dataset.dataset_kind) {
        openParams.set('input_kind', String(dataset.dataset_kind));
      }
      const openHref = `/dashboard?${openParams.toString()}`;
      if (dataset.status === 'ready') {
        actions.innerHTML = `
          <a class="ghost-link action-link-primary" href="${openHref}">Open</a>
          <form method="post" action="/dashboard/delete/${dataset.id}" data-confirm="Delete dataset '${dataset.file_name}'?" data-confirm-title="Delete dataset" data-confirm-label="Delete dataset">
            <button type="submit" class="danger-button">Delete</button>
          </form>
        `;
      } else if (dataset.status === 'processing') {
        actions.innerHTML = `
          <span class="ghost-link action-link-disabled" aria-disabled="true">Open</span>
          <form method="post" action="/dashboard/stop/${dataset.id}" data-confirm="Stop processing for '${dataset.file_name}'?" data-confirm-title="Stop processing" data-confirm-label="Stop processing">
            <button type="submit" class="danger-button">Stop</button>
          </form>
        `;
      } else if (dataset.status === 'queued') {
        actions.innerHTML = `
          <span class="ghost-link action-link-disabled" aria-disabled="true">Open</span>
          <form method="post" action="/dashboard/delete/${dataset.id}" data-confirm="Delete queued dataset '${dataset.file_name}'?" data-confirm-title="Delete dataset" data-confirm-label="Delete dataset">
            <button type="submit" class="danger-button">Delete</button>
          </form>
        `;
      } else if (dataset.status === 'failed' || dataset.status === 'stopped') {
        actions.innerHTML = `
          <form method="post" action="/dashboard/retry/${dataset.id}" data-loading-label="Retrying dataset processing">
            <button type="submit" class="warning-button">Retry</button>
          </form>
          <form method="post" action="/dashboard/delete/${dataset.id}" data-confirm="Delete dataset '${dataset.file_name}'?" data-confirm-title="Delete dataset" data-confirm-label="Delete dataset">
            <button type="submit" class="danger-button">Delete</button>
          </form>
        `;
      }
      actions.querySelectorAll('form[data-confirm]').forEach((form) => {
        form.addEventListener('submit', async (event) => {
          event.preventDefault();
          const accepted = await showConfirmDialog(form.dataset.confirm, {
            title: form.dataset.confirmTitle || 'Confirm action',
            confirmLabel: form.dataset.confirmLabel || 'Confirm',
          });
          if (accepted) {
            form.submit();
          }
        });
      });
    }
  };

  const pollQueue = async () => {
    try {
      const response = await fetch(url, {headers: {'Accept': 'application/json'}});
      if (!response.ok) return;
      const payload = await response.json();
      const datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
      datasets.forEach(updateQueueRow);
      const selectedDatasetId = selectedDatasetField ? selectedDatasetField.value : '';
      if (waitingPanel && selectedDatasetId) {
        const selected = datasets.find((dataset) => String(dataset.id) === String(selectedDatasetId));
        if (selected) {
          waitingPanel.innerHTML = `The dashboard queue is updating live. Current state: <strong>${selected.status_label}</strong>.`;
          if (selected.status === 'ready') {
            window.location.reload();
          }
        }
      }
    } catch (_error) {
      // Ignore transient polling errors and keep the current UI state.
    } finally {
      if (delay > 0) {
        window.setTimeout(pollQueue, delay);
      }
    }
  };

  if (url && delay > 0) {
    window.setTimeout(pollQueue, delay);
  }
}
