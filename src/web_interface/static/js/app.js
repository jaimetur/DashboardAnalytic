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

document.querySelectorAll('[data-horizontal-wheel-scroll]').forEach((container) => {
  container.addEventListener('wheel', (event) => {
    if (!event.shiftKey || container.scrollWidth <= container.clientWidth) return;
    event.preventDefault();
    container.scrollLeft += event.deltaY || event.deltaX;
  }, {passive: false});
});

document.querySelectorAll('[data-preview-table-filters]').forEach((filters) => {
  const panel = filters.closest('.dataset-preview-panel');
  const table = panel?.querySelector('[data-preview-filter-table]');
  const columnInput = filters.querySelector('[data-preview-column-filter]');
  const rowInput = filters.querySelector('[data-preview-row-filter]');
  const status = filters.querySelector('[data-preview-filter-status]');
  if (!table || !columnInput || !rowInput) return;

  const headers = Array.from(table.querySelectorAll('thead th'));
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const valueFilters = new Map();
  let openColumnMenu = null;
  const termsFor = (input) => String(input.value || '')
    .split(',')
    .map((term) => term.trim().toLocaleLowerCase())
    .filter(Boolean);
  const matchesAny = (value, terms) => !terms.length || terms.some((term) => value.includes(term));

  const applyPreviewFilters = () => {
    const columnTerms = termsFor(columnInput);
    const rowTerms = termsFor(rowInput);
    const visibleColumns = headers.map((header, index) => {
      const visible = matchesAny(header.textContent.toLocaleLowerCase(), columnTerms);
      header.hidden = !visible;
      rows.forEach((row) => {
        const cell = row.cells[index];
        if (cell) cell.hidden = !visible;
      });
      return visible;
    });
    let visibleRowCount = 0;
    rows.forEach((row) => {
      // Row filtering searches every original cell. It remains predictable even
      // when a separate column-name filter temporarily hides matching cells.
      const rowText = Array.from(row.cells).map((cell) => cell.textContent.toLocaleLowerCase()).join(' ');
      const matchesColumnValues = Array.from(valueFilters.entries()).every(([columnIndex, accepted]) => {
        const cellValue = String(row.cells[columnIndex]?.textContent || '').trim();
        return accepted.has(cellValue);
      });
      const visible = matchesAny(rowText, rowTerms) && matchesColumnValues;
      row.hidden = !visible;
      if (visible) visibleRowCount += 1;
    });
    if (status) {
      const visibleColumnCount = visibleColumns.filter(Boolean).length;
      const activeValueFilters = valueFilters.size ? ` · ${valueFilters.size} column filter${valueFilters.size === 1 ? '' : 's'} active` : '';
      status.textContent = `Showing ${visibleRowCount} of ${rows.length} rows · ${visibleColumnCount} of ${headers.length} columns${activeValueFilters}`;
    }
  };

  const closeColumnMenu = () => {
    if (!openColumnMenu) return;
    openColumnMenu.trigger.setAttribute('aria-expanded', 'false');
    openColumnMenu.menu.remove();
    openColumnMenu = null;
  };

  const setCheckboxes = (menu, checked) => {
    menu.querySelectorAll('[data-preview-value-option]').forEach((checkbox) => {
      checkbox.checked = checked;
    });
  };

  const openValueMenu = (header, trigger, columnIndex) => {
    if (openColumnMenu?.trigger === trigger) {
      closeColumnMenu();
      return;
    }
    closeColumnMenu();
    const values = Array.from(new Set(rows.map((row) => String(row.cells[columnIndex]?.textContent || '').trim())))
      .sort((left, right) => left.localeCompare(right, undefined, {numeric: true, sensitivity: 'base'}));
    const activeValues = valueFilters.get(columnIndex);
    const selectedValues = new Set(activeValues ? Array.from(activeValues) : values);
    const menu = document.createElement('section');
    menu.className = 'preview-column-filter-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filter ${trigger.dataset.columnLabel}`);

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'preview-column-filter-search';
    search.placeholder = 'Search values';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', `Search ${trigger.dataset.columnLabel} values`);

    const toolbar = document.createElement('div');
    toolbar.className = 'preview-column-filter-toolbar';
    const selectAll = document.createElement('button');
    selectAll.type = 'button';
    selectAll.textContent = 'Select all';
    const clearAll = document.createElement('button');
    clearAll.type = 'button';
    clearAll.textContent = 'Clear';
    toolbar.append(selectAll, clearAll);

    const options = document.createElement('div');
    options.className = 'preview-column-filter-options';
    values.forEach((value) => {
      const option = document.createElement('label');
      option.className = 'preview-column-filter-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = value;
      checkbox.checked = selectedValues.has(value);
      checkbox.setAttribute('data-preview-value-option', '');
      const caption = document.createElement('span');
      caption.textContent = value || '(Blank)';
      option.append(checkbox, caption);
      options.append(option);
    });

    const footer = document.createElement('div');
    footer.className = 'preview-column-filter-footer';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'preview-column-filter-cancel';
    cancel.textContent = 'Cancel';
    const apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'preview-column-filter-apply';
    apply.textContent = 'Apply';
    footer.append(cancel, apply);
    menu.append(search, toolbar, options, footer);
    document.body.append(menu);

    const positionMenu = () => {
      const bounds = trigger.getBoundingClientRect();
      const width = Math.min(300, window.innerWidth - 20);
      menu.style.width = `${width}px`;
      menu.style.left = `${Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10))}px`;
      const preferredTop = bounds.bottom + 5;
      const menuHeight = menu.offsetHeight;
      menu.style.top = `${preferredTop + menuHeight <= window.innerHeight - 10 ? preferredTop : Math.max(10, bounds.top - menuHeight - 5)}px`;
    };
    positionMenu();
    trigger.setAttribute('aria-expanded', 'true');
    openColumnMenu = {menu, trigger};

    search.addEventListener('input', () => {
      const term = search.value.trim().toLocaleLowerCase();
      options.querySelectorAll('.preview-column-filter-option').forEach((option) => {
        option.hidden = Boolean(term) && !option.textContent.toLocaleLowerCase().includes(term);
      });
    });
    selectAll.addEventListener('click', () => setCheckboxes(menu, true));
    clearAll.addEventListener('click', () => setCheckboxes(menu, false));
    cancel.addEventListener('click', closeColumnMenu);
    apply.addEventListener('click', () => {
      const accepted = new Set(Array.from(options.querySelectorAll('[data-preview-value-option]:checked')).map((checkbox) => checkbox.value));
      if (accepted.size === values.length) valueFilters.delete(columnIndex);
      else valueFilters.set(columnIndex, accepted);
      header.classList.toggle('has-value-filter', valueFilters.has(columnIndex));
      applyPreviewFilters();
      closeColumnMenu();
    });
    menu.addEventListener('click', (event) => event.stopPropagation());
    requestAnimationFrame(() => search.focus());
  };

  headers.forEach((header, columnIndex) => {
    const columnLabel = header.textContent.trim();
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'preview-column-filter-trigger';
    trigger.dataset.columnLabel = columnLabel;
    trigger.setAttribute('aria-label', `Filter ${columnLabel}`);
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    const caption = document.createElement('span');
    caption.textContent = columnLabel;
    const icon = document.createElement('span');
    icon.className = 'preview-column-filter-icon';
    icon.textContent = '▾';
    icon.setAttribute('aria-hidden', 'true');
    trigger.append(caption, icon);
    header.replaceChildren(trigger);
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      openValueMenu(header, trigger, columnIndex);
    });
  });

  columnInput.addEventListener('input', applyPreviewFilters);
  rowInput.addEventListener('input', applyPreviewFilters);
  document.addEventListener('click', closeColumnMenu);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeColumnMenu();
  });
  window.addEventListener('resize', closeColumnMenu);
  panel.querySelector('.dataset-preview-table-wrap')?.addEventListener('scroll', closeColumnMenu, {passive: true});
  applyPreviewFilters();
});

document.querySelectorAll('[data-catalogue-editor]').forEach((editor) => {
  const table = editor.querySelector('[data-catalogue-editor-table]');
  const saveForm = editor.querySelector('[data-catalogue-editor-save]');
  const reenumerate = editor.querySelector('[data-catalogue-reenumerate]');
  const contentField = editor.querySelector('[data-catalogue-editor-content]');
  const heading = editor.querySelector('[data-catalogue-editor-heading]');
  const copy = editor.querySelector('[data-catalogue-editor-copy]');
  const optionsLabel = editor.querySelector('[data-catalogue-editor-options-label]');
  const options = editor.querySelector('[data-catalogue-editor-options]');
  const apply = editor.querySelector('[data-catalogue-editor-apply]');
  const helper = editor.querySelector('.catalogue-editor-helper');
  const helperClose = editor.querySelector('[data-catalogue-editor-helper-close]');
  const filterBuilder = editor.querySelector('[data-catalogue-filter-builder]');
  const filterConditions = editor.querySelector('[data-catalogue-filter-conditions]');
  const addFilter = editor.querySelector('[data-catalogue-filter-add]');
  const chartPreview = editor.querySelector('[data-catalogue-chart-preview]');
  const chartPreviewDialog = chartPreview?.querySelector('.catalogue-chart-preview-dialog');
  const chartPreviewTitle = editor.querySelector('[data-catalogue-chart-preview-title]');
  const chartPreviewSummary = editor.querySelector('[data-catalogue-chart-preview-summary]');
  const chartPreviewTable = editor.querySelector('[data-catalogue-chart-preview-table]');
  const chartPreviewClose = editor.querySelector('[data-catalogue-chart-preview-close]');
  const chartPreviewTableWrap = chartPreviewTable?.closest('.table-wrap');
  const chartPreviewImage = editor.querySelector('[data-catalogue-chart-preview-image]');
  const chartPreviewImageContent = editor.querySelector('[data-catalogue-chart-preview-image-content]');
  const chartPreviewSandbox = editor.querySelector('[data-catalogue-chart-preview-sandbox]');
  const chartPreviewFields = editor.querySelector('[data-catalogue-chart-preview-fields]');
  const chartPreviewData = editor.querySelector('[data-catalogue-chart-preview-data]');
  const chartPreviewDataOverlay = editor.querySelector('[data-catalogue-chart-preview-data-overlay]');
  const chartPreviewDataPanel = editor.querySelector('[data-catalogue-chart-preview-data-panel]');
  const chartPreviewUpdate = editor.querySelector('[data-catalogue-chart-preview-update]');
  let chartPreviewImageUrl = '';
  let chartPreviewRow = null;
  let chartPreviewTimer = null;
  let chartPreviewDatasetPage = 0;
  const chartPreviewDatasetPageSize = 100;
  const chartPreviewDatasetFilters = new Map();
  let chartPreviewDatasetFilterMenu = null;
  if (!table || !saveForm || !contentField || !heading || !copy || !optionsLabel || !options || !apply || !helper) return;

  // The editor panel uses backdrop effects, which establish a containing block
  // for fixed descendants. Move the floating helper to the document root so
  // its viewport coordinates line up exactly with the active table cell.
  document.body.append(helper);

  let suggestions = {};
  try { suggestions = JSON.parse(editor.dataset.editorSuggestions || '{}'); } catch (_error) { suggestions = {}; }
  let activeCell = null;
  const catalogueHeaders = Array.from(table.querySelectorAll('thead th[data-catalogue-field], thead th'))
    .map((cell) => cell.textContent.trim())
    .filter((header) => header && header !== 'Row actions');
  const fieldColumns = new Set(['Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend']);
  const assistedFields = new Set(['Layout', 'CDR source', 'KPI', 'Chart type', 'Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend', 'Legend Position']);
  const groupingColumns = new Set(['Rows Aggregation', 'Column Aggregation']);
  const optionList = (field, cell) => {
    if (field === 'Layout') return suggestions.layouts || [];
    if (field === 'Chart type') return suggestions.chart_types || [];
    if (field === 'Legend Position') return suggestions.legend_positions || [];
    if (field === 'CDR source') return Object.keys(suggestions.columns || {}).map((source) => source.replace(/^cdr-/, 'CDR-').replace(/(^|-)\w/g, (letter) => letter.toUpperCase()));
    if (fieldColumns.has(field) || field === 'KPI') {
      const row = cell.closest('tr');
      const source = row?.querySelector('[data-catalogue-field="CDR source"]')?.textContent.trim().toLocaleLowerCase();
      return suggestions.columns?.[source] || [];
    }
    return [];
  };
  const helperCopy = (field) => {
    if (field === 'Layout') return 'Choose one of the layouts defined by the selected PowerPoint template. It replaces the current value.';
    if (field === 'Chart type') return 'Choose one supported chart type. It replaces the current value.';
    if (field === 'CDR source') return 'Choose the CDR source used to create this chart. It replaces the current value.';
    if (field === 'KPI') return 'Choose a processed field from the CDR source. It replaces the current value.';
    if (field === 'Legend') return 'Select one or more CDR fields to use as the displayed legend labels. Values are stored as a comma-separated list.';
    if (field === 'Legend Position') return 'Choose where the legend is drawn: Top or Bottom uses a horizontal row; Left or Right uses a vertical column.';
    if (field === 'Filters') return 'Build complete conditions from a processed CDR field, operator and real observed value. Conditions are joined with semicolons (AND), and the cell remains manually editable.';
    if (field === 'Rows Aggregation') return 'Select one or more dimensions for the chart category axis or table rows. They are appended with ×.';
    if (field === 'Column Aggregation') return 'Select one or more dimensions for comparison series or table columns. They are appended with ×.';
    return 'This value can be edited directly. Select Layout, Chart type, Filters or Grouping for contextual suggestions.';
  };
  const selectedSource = (cell) => cell?.closest('tr')?.querySelector('[data-catalogue-field="CDR source"]')?.textContent.trim().toLocaleLowerCase() || '';
  const filterOperators = [
    ['=', 'Equals (=)'], ['!=', 'Not equal (!=)'], ['CONTAINS', 'Contains'], ['NOT CONTAINS', 'Not contains'],
    ['IN', 'In list (IN)'], ['NOT IN', 'Not in list (NOT IN)'], ['<', 'Less than (<)'], ['<=', 'Less than or equal (≤)'],
    ['>', 'Greater than (>)'], ['>=', 'Greater than or equal (≥)'],
  ];
  const parseFilterConditions = (raw) => String(raw || '').replace(/\u00a0/g, ' ').split(';').map((clause) => {
    const match = clause.trim().match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i);
    if (!match) return null;
    const [, field, operator, value] = match;
    return { field: field.trim(), operator: operator.replace(/\s+/g, ' ').toUpperCase(), value: value.trim().replace(/^\((.*)\)$/, '$1') };
  }).filter(Boolean);
  const syncFilterCell = () => {
    if (!activeCell || activeCell.dataset.catalogueField !== 'Filters' || !filterConditions) return;
    const clauses = Array.from(filterConditions.querySelectorAll('[data-filter-condition]')).map((row) => {
      const field = row.querySelector('[data-filter-field]')?.value.trim();
      const operator = row.querySelector('[data-filter-operator]')?.value.trim();
      const rawValue = row.querySelector('[data-filter-value]')?.value.trim();
      if (!field || !operator || !rawValue) return '';
      const listOperator = ['IN', 'NOT IN', 'CONTAINS', 'NOT CONTAINS'].includes(operator);
      const value = listOperator && rawValue.includes(',') && !/^\(.+\)$/.test(rawValue) ? `(${rawValue})` : rawValue;
      return `${field} ${operator} ${value}`;
    }).filter(Boolean);
    activeCell.textContent = clauses.join('; ');
  };
  const addFilterCondition = (condition = {}) => {
    if (!filterConditions || !activeCell) return;
    const source = selectedSource(activeCell);
    const fields = suggestions.columns?.[source] || [];
    const row = document.createElement('div');
    row.className = 'catalogue-filter-condition';
    row.dataset.filterCondition = '';
    const field = document.createElement('select');
    field.dataset.filterField = '';
    field.dataset.searchableSelect = '';
    field.setAttribute('aria-label', 'Filter field');
    field.append(new Option('Choose field', ''));
    fields.forEach((value) => field.add(new Option(value, value)));
    const normalizedOption = (select, requested) => {
      const normalize = (value) => String(value || '').toLocaleLowerCase().replace(/[^a-z0-9]+/g, '');
      return Array.from(select.options).find((option) => normalize(option.value) === normalize(requested))?.value || requested || '';
    };
    field.value = normalizedOption(field, condition.field);
    const operator = document.createElement('select');
    operator.dataset.filterOperator = '';
    operator.dataset.searchableSelect = '';
    operator.setAttribute('aria-label', 'Filter operator');
    filterOperators.forEach(([value, label]) => operator.add(new Option(label, value)));
    operator.value = normalizedOption(operator, condition.operator || '=');
    const value = document.createElement('input');
    const list = document.createElement('datalist');
    const listId = `catalogue-filter-values-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    value.type = 'text'; value.dataset.filterValue = ''; value.placeholder = 'Choose or type a value'; value.setAttribute('list', listId);
    list.id = listId;
    let valueRequest = 0;
    const updateValues = async () => {
      const request = ++valueRequest;
      const selectedField = field.value;
      list.replaceChildren();
      if (!source || !selectedField) return;
      try {
        const query = new URLSearchParams({ source, column: selectedField });
        const response = await fetch(`/admin/catalogue-filter-values?${query.toString()}`, { credentials: 'same-origin' });
        const payload = response.ok ? await response.json() : { values: [] };
        if (request !== valueRequest) return;
        const available = Array.isArray(payload.values) ? payload.values : [];
        list.replaceChildren(...available.map((item) => new Option(item, item)));
      } catch (_error) {
        // A value may always be entered manually if contextual values are unavailable.
      }
    };
    value.value = condition.value || '';
    updateValues();
    const remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'catalogue-filter-remove'; remove.textContent = '−'; remove.title = 'Remove condition'; remove.setAttribute('aria-label', 'Remove filter condition');
    field.addEventListener('change', () => { updateValues(); syncFilterCell(); });
    operator.addEventListener('change', syncFilterCell);
    value.addEventListener('input', syncFilterCell);
    remove.addEventListener('click', () => { row.remove(); syncFilterCell(); });
    row.append(field, operator, value, remove, list);
    filterConditions.append(row);
    setupSearchableSingleSelects();
    // The visual searchable controls are sibling shells. Hydrate them from
    // the native select after they have been mounted, so existing clauses are
    // visible immediately rather than showing their search placeholder.
    window.requestAnimationFrame(() => {
      [field, operator].forEach((select) => {
        const input = select.nextElementSibling?.querySelector('.searchable-select-input');
        if (input) input.value = select.selectedOptions[0]?.textContent?.trim() || '';
      });
      value.value = condition.value || '';
    });
  };
  const populateFilterBuilder = (cell) => {
    if (!filterBuilder || !filterConditions) return;
    filterConditions.replaceChildren();
    const conditions = parseFilterConditions(cell.textContent);
    (conditions.length ? conditions : [{}]).forEach(addFilterCondition);
    filterBuilder.hidden = false;
  };
  const hideCellAssistance = () => {
    helper.hidden = true;
    delete helper.dataset.catalogueAssistanceField;
    helper.classList.remove('catalogue-editor-menu-open');
    helper.querySelectorAll('.searchable-select-menu, .multiselect-menu').forEach((menu) => {
      menu.style.removeProperty('position');
      menu.style.removeProperty('left');
      menu.style.removeProperty('top');
      menu.style.removeProperty('bottom');
      menu.style.removeProperty('right');
      menu.style.removeProperty('width');
      menu.style.removeProperty('max-height');
    });
  };
  const placeAssistanceMenu = (target) => {
    const shell = target.closest?.('.searchable-select-shell, .multiselect-shell');
    const menu = shell?.querySelector('.searchable-select-menu:not([hidden]), .multiselect-menu:not([hidden])');
    const editorPanel = editor.closest('.slides-templates-editor-panel');
    if (!shell || !menu || !editorPanel) return;
    const panelBounds = editorPanel.getBoundingClientRect();
    const shellBounds = shell.getBoundingClientRect();
    const gap = 7;
    // The editor panel can be taller than the viewport.  Constrain the menu
    // to the visible part of both, otherwise a fixed menu can be placed below
    // the screen and look as though it refused to open.
    const visiblePanelTop = Math.max(8, panelBounds.top);
    const visiblePanelBottom = Math.min(window.innerHeight - 8, panelBounds.bottom);
    const below = Math.max(0, visiblePanelBottom - shellBounds.bottom - gap);
    const above = Math.max(0, shellBounds.top - visiblePanelTop - gap);
    const openBelow = below >= above;
    const availableHeight = openBelow ? below : above;
    // A compact, scrollable list remains usable even when there is little
    // room beside the Cell Assistance dialog.
    const maxHeight = Math.max(96, Math.min(360, availableHeight));
    const width = Math.max(180, Math.min(shellBounds.width, panelBounds.right - shellBounds.left));
    menu.style.position = 'fixed';
    menu.style.left = `${Math.max(panelBounds.left, Math.min(shellBounds.left, panelBounds.right - width))}px`;
    menu.style.right = 'auto';
    menu.style.width = `${width}px`;
    menu.style.maxHeight = `${maxHeight}px`;
    if (openBelow) {
      menu.style.top = `${shellBounds.bottom + gap}px`;
      menu.style.bottom = 'auto';
    } else {
      menu.style.bottom = `${Math.max(0, window.innerHeight - shellBounds.top + gap)}px`;
      menu.style.top = 'auto';
    }
    helper.classList.add('catalogue-editor-menu-open');
  };
  const positionCellAssistance = (cell) => {
    helper.hidden = false;
    window.requestAnimationFrame(() => {
      const cellBounds = cell.getBoundingClientRect();
      const gap = 6;
      const helperBounds = helper.getBoundingClientRect();
      const helperWidth = helperBounds.width;
      const helperHeight = helperBounds.height;
      const cellCenterX = cellBounds.left + (cellBounds.width / 2);
      const isLeftHalf = cellCenterX < window.innerWidth / 2;
      const isTopHalf = cellBounds.top + (cellBounds.height / 2) < window.innerHeight / 2;
      // Anchor diagonally from the active cell. This keeps the source visible
      // while making the assistance panel unambiguously belong to that cell.
      let left = isLeftHalf ? cellBounds.right + gap : cellBounds.left - helperWidth - gap;
      let top = isTopHalf ? cellBounds.bottom + gap : cellBounds.top - helperHeight - gap;

      // Preserve the diagonal anchor whenever possible; only constrain it at
      // a viewport edge so the panel never becomes inaccessible.
      left = Math.min(Math.max(gap, left), window.innerWidth - helperWidth - gap);
      top = Math.min(Math.max(gap, top), window.innerHeight - helperHeight - gap);
      helper.style.left = `${left}px`;
      helper.style.top = `${top}px`;
    });
  };
  const selectCell = (cell) => {
    if (activeCell) activeCell.classList.remove('is-selected');
    activeCell = cell;
    activeCell.classList.add('is-selected');
    const field = cell.dataset.catalogueField || '';
    if (!assistedFields.has(field)) {
      hideCellAssistance();
      return;
    }
    helper.dataset.catalogueAssistanceField = field;
    heading.textContent = field || 'Selected cell';
    copy.textContent = helperCopy(field);
    const values = optionList(field, cell);
    const allowsMultiple = fieldColumns.has(field);
    options.multiple = allowsMultiple;
    options.size = allowsMultiple ? 11 : 1;
    options.replaceChildren();
    const existingValues = new Set(
      (allowsMultiple
        ? cell.textContent.split(groupingColumns.has(field) ? /(?:\s*×\s*|\s+[xX]\s+)/ : /\s*,\s*/)
        : [cell.textContent])
        .map((value) => value.trim())
        .filter(Boolean),
    );
    const normaliseOptionValue = (value) => String(value || '')
      .trim().toLocaleLowerCase().replace(/[\s_-]+/g, ' ');
    const hasExistingValue = (value) => Array.from(existingValues).some(
      (existing) => normaliseOptionValue(existing) === normaliseOptionValue(value),
    );
    if (values.length) {
      values.forEach((value) => options.add(new Option(value, value, false, hasExistingValue(value))));
      // Explicitly assign the matching value as well as marking its option.
      // This keeps the searchable single-select hydrated after it is rebuilt.
      if (!allowsMultiple) {
        const selected = Array.from(options.options).find((option) => hasExistingValue(option.value));
        options.value = selected?.value || '';
      }
    } else {
      options.add(new Option('No contextual values are defined for this field. Edit it manually.', '', true, false));
      options.options[0].disabled = true;
    }
    optionsLabel.hidden = false;
    apply.hidden = values.length === 0;
    if (field === 'Filters') {
      optionsLabel.hidden = true;
      apply.hidden = true;
      populateFilterBuilder(cell);
    } else if (filterBuilder) {
      filterBuilder.hidden = true;
    }
    options.dispatchEvent(new Event('searchable-select:options-updated'));
    options.dispatchEvent(new Event('multiselect:options-updated'));
    // A preceding single-value field removes the custom control; recreate it
    // whenever this cell switches Available values back to multi-select.
    setupCustomMultiSelects();
    setupSearchableSingleSelects();
    if (!allowsMultiple) {
      window.requestAnimationFrame(() => {
        const input = options.nextElementSibling?.querySelector('.searchable-select-input');
        if (input) input.value = options.selectedOptions[0]?.textContent?.trim() || '';
      });
    }
    positionCellAssistance(cell);
  };
  const selectedCellFromEvent = (event) => {
    const cell = event.target.closest?.('[data-catalogue-field]');
    if (!cell) return null;
    const viewport = table.closest('.table-wrap');
    if (!viewport) return cell;
    const viewportBounds = viewport.getBoundingClientRect();
    const cellBounds = cell.getBoundingClientRect();
    const cellIsVisible = (
      cellBounds.right > viewportBounds.left
      && cellBounds.left < viewportBounds.right
      && cellBounds.bottom > viewportBounds.top
      && cellBounds.top < viewportBounds.bottom
    );
    const clickIsVisible = (
      typeof event.clientX !== 'number'
      || (
        event.clientX >= viewportBounds.left
        && event.clientX <= viewportBounds.right
        && event.clientY >= viewportBounds.top
        && event.clientY <= viewportBounds.bottom
      )
    );
    return cellIsVisible && clickIsVisible ? cell : null;
  };

  const updateRowActionStates = () => {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    rows.forEach((row, index) => {
      const action = (name) => row.querySelector(`[data-catalogue-row-action="${name}"]`);
      const up = action('up');
      const down = action('down');
      const remove = action('delete');
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === rows.length - 1;
      if (remove) remove.disabled = rows.length <= 1;
    });
  };
  const sharedSlideFields = ['Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout'];
  const sharedValueKey = (field) => `catalogueShared${field.replace(/[^a-z0-9]+/gi, '')}`;
  const rowValue = (row, field) => (
    row.querySelector(`[data-catalogue-field="${field}"]`)?.textContent.trim()
    ?? row.dataset[sharedValueKey(field)]
    ?? ''
  );
  const rowValues = (row) => Object.fromEntries(catalogueHeaders.map((header) => [header, rowValue(row, header)]));
  const createActionButton = (label, action, title, className = '') => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.dataset.catalogueRowAction = action;
    button.title = title;
    if (className) button.className = className;
    return button;
  };
  const createCatalogueRow = (sourceRow, blankChartFields = false) => {
    const source = sourceRow instanceof HTMLTableRowElement ? rowValues(sourceRow) : (sourceRow || {});
    const retained = ['Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout'];
    const row = document.createElement('tr');
    const actions = document.createElement('td');
    actions.className = 'catalogue-row-actions';
    actions.dataset.catalogueRowActions = '';
    actions.append(
      createActionButton('↑', 'up', 'Move row up'),
      createActionButton('↓', 'down', 'Move row down'),
      createActionButton('+', 'insert', 'Insert a row below'),
      createActionButton('−', 'delete', 'Delete row', 'catalogue-row-delete'),
      ...(String(source['CDR source'] || '').trim() ? [createActionButton('▥', 'preview', 'Preview chart data')] : []),
      ...(String(source['CDR source'] || '').trim() ? [createActionButton('👁', 'chart-preview', 'Preview generated chart')] : []),
    );
    row.append(actions);
    catalogueHeaders.forEach((header) => {
      const cell = document.createElement('td');
      cell.contentEditable = 'true';
      cell.spellcheck = false;
      cell.dataset.catalogueField = header;
      // Only a newly inserted sibling starts with blank chart fields. Rows
      // rebuilt for grouping, sorting or saving must retain every definition.
      cell.textContent = blankChartFields && !retained.includes(header) ? '' : (source[header] || '');
      row.append(cell);
    });
    return row;
  };
  const sortCatalogueRows = (rows) => rows.map((row, position) => {
    const slide = Number(row.Slide);
    return {row, position, slide: Number.isInteger(slide) && slide > 0 ? slide : null};
  }).sort((left, right) => {
    if (left.slide === null && right.slide === null) return left.position - right.position;
    if (left.slide === null) return 1;
    if (right.slide === null) return -1;
    return left.slide - right.slide || left.position - right.position;
  }).map(({row}) => row);
  const mergeSlideMetadataCells = () => {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    let start = 0;
    let slideBlockIndex = 0;
    while (start < rows.length) {
      const slide = rowValue(rows[start], 'Slide');
      let end = start + 1;
      while (end < rows.length && rowValue(rows[end], 'Slide') === slide) end += 1;
      const block = rows.slice(start, end);
      const tone = slideBlockIndex % 2 === 0 ? 'catalogue-slide-tone-purple' : 'catalogue-slide-tone-pink';
      block.forEach((row) => row.classList.add(tone));
      if (slide && block.length > 1) {
        sharedSlideFields.forEach((field) => {
          const master = block[0].querySelector(`[data-catalogue-field="${field}"]`);
          if (!master) return;
          const value = master.textContent.trim();
          const key = sharedValueKey(field);
          block.forEach((row) => { row.dataset[key] = value; });
          master.rowSpan = block.length;
          master.classList.add('catalogue-shared-slide-cell');
          master.addEventListener('input', () => {
            block.forEach((row) => { row.dataset[key] = master.textContent.trim(); });
          });
          block.slice(1).forEach((row) => row.querySelector(`[data-catalogue-field="${field}"]`)?.remove());
        });
      }
      start = end;
      slideBlockIndex += 1;
    }
  };
  const renderCatalogueRows = (rows) => {
    const body = table.querySelector('tbody');
    if (!body) return;
    // Do not pass createCatalogueRow directly to map: map also supplies the
    // row index, which must never be interpreted as blankChartFields.
    body.replaceChildren(...sortCatalogueRows(rows).map((row) => createCatalogueRow(row)));
    mergeSlideMetadataCells();
    updateRowActionStates();
  };
  const normaliseCatalogueRows = () => {
    const body = table.querySelector('tbody');
    if (!body) return;
    renderCatalogueRows(Array.from(body.querySelectorAll('tr')).map(rowValues));
  };
  const serialiseCatalogueContent = () => {
    const escapeCsv = (value) => {
      const text = String(value || '').replace(/\r?\n/g, '\\n');
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    normaliseCatalogueRows();
    const rows = Array.from(table.querySelectorAll('tbody tr')).map((row) => (
      catalogueHeaders.map((header) => escapeCsv(rowValue(row, header))).join(',')
    ));
    return [catalogueHeaders.map(escapeCsv).join(','), ...rows].join('\n');
  };
  let savedCatalogueContent = '';
  const hasUnsavedCatalogueChanges = () => serialiseCatalogueContent() !== savedCatalogueContent;
  const renderChartPreview = (payload) => {
    if (!chartPreview || !chartPreviewTable || !chartPreviewTitle || !chartPreviewSummary) return;
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const columns = Array.isArray(payload.summary?.columns) ? payload.summary.columns : [];
    chartPreviewTitle.textContent = `${payload.chart_title || 'Selected chart'} · ${payload.source || ''}`;
    chartPreviewSummary.textContent = `${payload.summary?.matched_rows ?? 0} matching rows from ${payload.summary?.source_rows ?? 0}; showing ${payload.summary?.shown_rows ?? 0}. Filters: ${payload.filters || 'No filters'}.`;
    chartPreviewTableWrap?.removeAttribute('hidden');
    if (chartPreviewImageUrl) { URL.revokeObjectURL(chartPreviewImageUrl); chartPreviewImageUrl = ''; }
    if (chartPreviewImageContent) chartPreviewImageContent.removeAttribute('src');
    if (chartPreviewImage) chartPreviewImage.hidden = true;
    if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
    chartPreviewTable.innerHTML = columns.length
      ? `<thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map((item) => `<tr>${columns.map((column) => `<td>${escapeHtml(item[column])}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${columns.length}">No rows match this chart definition.</td></tr>`}</tbody>`
      : '<tbody><tr><td>No chart fields are available to preview.</td></tr></tbody>';
    chartPreview.hidden = false;
  };
  const closeChartPreview = () => { if (chartPreview) chartPreview.hidden = true; };
  chartPreviewClose?.addEventListener('click', closeChartPreview);
  chartPreview?.addEventListener('click', (event) => { if (event.target === chartPreview) closeChartPreview(); });
  const previewChartData = async (row, definition = {}) => {
    const endpoint = editor.dataset.chartPreviewUrl;
    if (!endpoint) return;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(row);
    if (rowIndex < 0) return;
    const button = row.querySelector('[data-catalogue-row-action="preview"]');
    if (button) button.disabled = true;
    showLoadingOverlay('Generating Chart Data Preview', 'Please wait while the Chart Data Preview is generated.');
    try {
      const response = await fetch(endpoint, {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({catalogue_content: serialiseCatalogueContent(), row_index: rowIndex, definition}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to preview chart data.');
      renderChartPreview(payload);
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to preview chart data.', {title: 'Chart Data Preview', tone: 'error'});
    } finally {
      hideLoadingOverlay();
      if (button) button.disabled = false;
    }
  };
  const previewDefinition = () => Object.fromEntries(Array.from(chartPreviewFields?.querySelectorAll('[name]') || []).map((control) => {
    if (!control.multiple) return [control.name, control.value];
    const separator = control.name === 'legend' ? ', ' : ' × ';
    return [control.name, Array.from(control.selectedOptions).map((option) => option.value).filter(Boolean).join(separator)];
  }));
  const previewDefinitionFromRow = (row) => ({
    chart_type: rowValue(row, 'Chart type'), chart_title: rowValue(row, 'Chart Tittle'), cdr_source: rowValue(row, 'CDR source'),
    kpi: rowValue(row, 'KPI'), filters: rowValue(row, 'Filters'), grouping_rows: rowValue(row, 'Rows Aggregation'),
    grouping_columns: rowValue(row, 'Column Aggregation'), legend: rowValue(row, 'Legend'), legend_position: rowValue(row, 'Legend Position'),
  });
  const renderChartPreviewSandbox = (row, definition = null) => {
    if (!chartPreviewSandbox || !chartPreviewFields) return;
    const current = definition || previewDefinitionFromRow(row);
    const regenerate = () => {
      if (chartPreviewTimer) window.clearTimeout(chartPreviewTimer);
      chartPreviewTimer = window.setTimeout(() => previewGeneratedChart(row, previewDefinition(), false), 350);
    };
    createInteractiveChartPreviewControls(chartPreviewFields, current, {
      columnsBySource: suggestions.columns,
      fields: [
        ['chart_type', 'Chart Type'], ['chart_title', 'Chart Tittle'], ['cdr_source', 'CDR Source'], ['kpi', 'KPI'], ['filters', 'Filters'],
        ['grouping_rows', 'Rows'], ['grouping_columns', 'Columns'], ['legend', 'Legend'], ['legend_position', 'Legend Position'],
      ],
      textFields: {chart_title: true},
      // Keep these option sets identical to the persisted Chart Viewer.
      chartTypes: ['100% Stacked Vertical Bars', 'Count Stacked Horizontal Bars', 'CDF Line', 'Scatter', 'Table', 'Distribution Stacked Vertical Bars', 'Threshold Stacked Vertical Bars', 'Average Vertical Bars', 'Median Vertical Bars'],
      cdrSources: ['CDR-Data', 'CDR-Voice', 'CDR-Speech'],
      legendPositions: ['Top', 'Bottom', 'Left', 'Right'],
      onChange: regenerate,
      onSourceChange: (next) => {
        renderChartPreviewSandbox(row, next);
        regenerate();
      },
    });
    chartPreviewSandbox.hidden = false;
  };
  const previewGeneratedChart = async (row, definition = {}, showOverlay = true) => {
    const endpoint = editor.dataset.chartImagePreviewUrl;
    if (!endpoint) return;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(row);
    if (rowIndex < 0) return;
    // serialiseCatalogueContent normalises/rebuilds editor rows. Resolve the
    // authoritative replacement row immediately afterwards, then initialise
    // the preview from those values rather than the stale click target.
    const catalogueContent = serialiseCatalogueContent();
    const resolvedRow = Array.from(table.querySelectorAll('tbody tr'))[rowIndex] || row;
    const rowDefinition = {...previewDefinitionFromRow(resolvedRow), ...definition};
    const button = row.querySelector('[data-catalogue-row-action="chart-preview"]');
    if (button) button.disabled = true;
    if (showOverlay) showLoadingOverlay('Generating Chart Preview', 'Please wait while the chart preview is generated.');
    try {
      const response = await fetch(endpoint, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({catalogue_content: catalogueContent, row_index: rowIndex, definition: rowDefinition})});
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Unable to preview the generated chart.');
      }
      const image = await response.blob();
      if (chartPreviewImageUrl) URL.revokeObjectURL(chartPreviewImageUrl);
      chartPreviewImageUrl = URL.createObjectURL(image);
      if (chartPreviewImageContent) chartPreviewImageContent.src = chartPreviewImageUrl;
      if (chartPreviewImage) chartPreviewImage.hidden = false;
      if (chartPreviewTableWrap) chartPreviewTableWrap.hidden = true;
      if (chartPreviewTitle) chartPreviewTitle.textContent = `Generated chart preview · ${rowDefinition.chart_title || rowValue(row, 'Slide Tittle') || 'Selected chart'}`;
      if (chartPreviewSummary) chartPreviewSummary.textContent = 'This is the chart image produced by the current unsaved template definition.';
      if (showOverlay) {
        chartPreviewDialog?.classList.remove('is-dataset-only');
        chartPreviewRow = resolvedRow;
        renderChartPreviewSandbox(chartPreviewRow, rowDefinition);
      }
      if (chartPreview) chartPreview.hidden = false;
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to preview the generated chart.', {title: 'Generated Chart Preview', tone: 'error'});
    } finally {
      if (showOverlay) hideLoadingOverlay();
      if (button) button.disabled = false;
    }
  };
  chartPreviewUpdate?.addEventListener('click', () => {
    if (!chartPreviewRow) return;
    const mapping = {chart_title: 'Chart Tittle', chart_type: 'Chart type', cdr_source: 'CDR source', kpi: 'KPI', filters: 'Filters', grouping_rows: 'Rows Aggregation', grouping_columns: 'Column Aggregation', legend: 'Legend', legend_position: 'Legend Position'};
    Object.entries(previewDefinition()).forEach(([key, value]) => { const cell = Array.from(chartPreviewRow.querySelectorAll('[data-catalogue-field]')).find((item) => item.dataset.catalogueField === mapping[key]); if (cell) cell.textContent = value; });
    showInfoDialog('The current preview values have been applied to this template row. Save the template to persist them.', {title: 'Template updated'});
  });
  chartPreviewData?.addEventListener('click', async () => {
    if (!chartPreviewRow) return;
    const endpoint = editor.dataset.chartPreviewUrl;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(chartPreviewRow);
    if (!endpoint || rowIndex < 0 || !chartPreviewDataPanel) return;
    chartPreviewData.disabled = true;
    chartPreviewDatasetPage = 0;
    chartPreviewDatasetFilters.clear();
    showLoadingOverlay('Loading Filtered Dataset', 'Please wait while the filtered dataset is prepared.');
    try {
      const activeDefinition = chartPreviewSandbox && !chartPreviewSandbox.hidden ? previewDefinition() : {};
      const requestBody = (page) => ({catalogue_content: serialiseCatalogueContent(), row_index: rowIndex, definition: activeDefinition, page, page_size: chartPreviewDatasetPageSize, column_filters: Object.fromEntries(Array.from(chartPreviewDatasetFilters.entries()).map(([column, values]) => [column, Array.from(values)]))});
      const response = await fetch(endpoint, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestBody(0))});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to load filtered dataset.');
      const renderPage = async (page) => {
        const request = await fetch(endpoint, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestBody(page))});
        const next = await request.json().catch(() => ({}));
        if (!request.ok) throw new Error(next.detail || 'Unable to load filtered dataset.');
        chartPreviewDatasetPage = page;
        renderDataset(next);
      };
      const renderDataset = (dataset) => {
        const columns = dataset.columns || dataset.summary?.columns || [];
        const rows = dataset.rows || [];
        const visibleRows = Number(dataset.summary?.visible_rows ?? rows.length);
        const sourceRows = Number(dataset.summary?.source_rows ?? 0);
        const matchedRows = Number(dataset.summary?.matched_rows ?? visibleRows);
        const pageCount = Math.max(1, Math.ceil(visibleRows / chartPreviewDatasetPageSize));
        const tableNode = document.createElement('table');
        const header = document.createElement('tr');
        columns.forEach((column) => {
          const cell = document.createElement('th'); const button = document.createElement('button'); button.type = 'button'; button.className = 'report-chart-viewer-column-filter';
          button.textContent = `${column} ▾`; button.classList.toggle('is-filtered', chartPreviewDatasetFilters.has(column));
          button.addEventListener('click', () => {
            chartPreviewDatasetFilterMenu?.remove();
            const values = (dataset.filter_values?.[column] || []).map(String); const selected = new Set(chartPreviewDatasetFilters.get(column) || values);
            const menu = document.createElement('section'); menu.className = 'report-chart-preview-select-menu report-chart-viewer-column-filter-menu';
            const search = document.createElement('input'); search.type = 'search'; search.placeholder = `Search ${column}`;
            const options = document.createElement('div'); options.className = 'report-chart-preview-select-options';
            const draw = () => { const query = search.value.toLocaleLowerCase(); options.replaceChildren(...values.filter((value) => !query || value.toLocaleLowerCase().includes(query)).map((value) => { const item = document.createElement('label'); item.className = 'report-chart-preview-select-option is-multiple'; const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(value); const text = document.createElement('span'); text.textContent = value || '(Blanks)'; check.addEventListener('change', () => { if (check.checked) selected.add(value); else selected.delete(value); if (selected.size === values.length) chartPreviewDatasetFilters.delete(column); else chartPreviewDatasetFilters.set(column, selected); menu.remove(); renderPage(0).catch((error) => showInfoDialog(error.message, {title: 'Filtered dataset', tone: 'error'})); }); item.append(check, text); return item; })); };
            search.addEventListener('input', draw); menu.append(search, options); document.body.append(menu); chartPreviewDatasetFilterMenu = menu; const bounds = button.getBoundingClientRect(); menu.style.left = `${Math.max(8, Math.min(bounds.left, window.innerWidth - 380))}px`; menu.style.top = `${Math.min(bounds.bottom + 4, window.innerHeight - 310)}px`; draw(); search.focus();
          });
          cell.append(button); header.append(cell);
        });
        const thead = document.createElement('thead'); thead.append(header); tableNode.append(thead);
        const body = document.createElement('tbody');
        rows.forEach((row) => { const line = document.createElement('tr'); columns.forEach((column) => { const cell = document.createElement('td'); cell.textContent = row[column] ?? ''; line.append(cell); }); body.append(line); });
        tableNode.append(body);
        const pager = document.createElement('nav'); pager.className = 'report-chart-viewer-data-pager';
        const add = (label, target, title) => { const control = document.createElement('button'); control.type = 'button'; control.textContent = label; control.title = title; control.disabled = target === chartPreviewDatasetPage; control.addEventListener('click', () => renderPage(target).catch((error) => showInfoDialog(error.message, {title: 'Filtered dataset', tone: 'error'}))); pager.append(control); };
        add('⏮', 0, 'First page'); add('←', Math.max(0, chartPreviewDatasetPage - 1), 'Previous page');
        const label = document.createElement('span'); label.textContent = `Page ${chartPreviewDatasetPage + 1} / ${pageCount}`; pager.append(label);
        add('→', Math.min(pageCount - 1, chartPreviewDatasetPage + 1), 'Next page'); add('⏭', pageCount - 1, 'Last page');
        const summary = document.createElement('p'); summary.className = 'form-note';
        summary.textContent = `${sourceRows} total dataset rows · ${matchedRows} chart-filtered rows · ${visibleRows} visible after column filters · ${rows.length} rows shown on this page`;
        // Only the table body scrolls.  Keep the result context and page
        // controls in sight while inspecting a long page of rows.
        const scrollArea = document.createElement('div'); scrollArea.className = 'report-chart-viewer-data-scroll';
        scrollArea.append(tableNode);
        chartPreviewDataPanel.replaceChildren(summary, pager, scrollArea);
      };
      renderDataset(payload);
      if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
      if (chartPreview) chartPreview.hidden = false;
      if (chartPreviewDataOverlay) chartPreviewDataOverlay.hidden = false;
    } catch (error) { showInfoDialog(error instanceof Error ? error.message : 'Unable to load filtered dataset.', {title: 'Filtered dataset', tone: 'error'}); }
    finally { hideLoadingOverlay(); chartPreviewData.disabled = false; }
  });
  chartPreviewDataOverlay?.addEventListener('click', (event) => {
    if (event.target === chartPreviewDataOverlay || event.target.closest('[data-catalogue-chart-preview-data-close]')) {
      chartPreviewDataOverlay.hidden = true;
      chartPreviewDatasetFilterMenu?.remove(); chartPreviewDatasetFilterMenu = null;
      if (chartPreviewDialog?.classList.contains('is-dataset-only')) {
        chartPreviewDialog.classList.remove('is-dataset-only');
        if (chartPreview) chartPreview.hidden = true;
      } else if (chartPreviewSandbox) chartPreviewSandbox.hidden = false;
    }
  });
  document.addEventListener('click', (event) => {
    if (chartPreviewDatasetFilterMenu && !chartPreviewDatasetFilterMenu.contains(event.target) && !event.target.closest('.report-chart-viewer-column-filter')) {
      chartPreviewDatasetFilterMenu.remove(); chartPreviewDatasetFilterMenu = null;
    }
  });
  table.addEventListener('click', async (event) => {
    const button = event.target.closest?.('[data-catalogue-row-action]');
    if (!button) return;
    event.preventDefault();
    const row = button.closest('tr');
    const body = row?.parentElement;
    if (!row || !body) return;
    const action = button.dataset.catalogueRowAction;
    if (action === 'preview') {
      chartPreviewRow = row;
      chartPreviewDialog?.classList.add('is-dataset-only');
      if (chartPreviewTitle) chartPreviewTitle.textContent = `Filtered dataset · ${rowValue(row, 'Chart Tittle') || rowValue(row, 'Slide Tittle') || 'Selected chart'}`;
      if (chartPreviewSummary) chartPreviewSummary.textContent = 'The complete chart-filtered dataset is available in paginated pages.';
      if (chartPreviewImage) chartPreviewImage.hidden = true;
      if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
      if (chartPreviewTableWrap) chartPreviewTableWrap.hidden = true;
      showLoadingOverlay('Loading Chart Data Preview', 'Please wait while the selected chart dataset is loaded.');
      chartPreviewData?.click();
      return;
    }
    if (action === 'chart-preview') {
      await previewGeneratedChart(row);
      return;
    }
    if (action === 'insert') {
      const slide = rowValue(row, 'Slide');
      const nextRow = row.nextElementSibling;
      const isLastChartOfSlide = !nextRow || rowValue(nextRow, 'Slide') !== slide;
      const choice = isLastChartOfSlide ? await showCatalogueInsertChoice(slide) : 'chart';
      if (!choice) return;
      if (choice === 'chart') {
        const inserted = createCatalogueRow(row, true);
        body.insertBefore(inserted, row.nextElementSibling);
        normaliseCatalogueRows();
        return;
      }
      const currentSlide = Number(slide);
      if (!Number.isInteger(currentSlide) || currentSlide < 1) return;
      const rows = Array.from(body.querySelectorAll('tr')).map(rowValues);
      const rowIndex = Array.from(body.querySelectorAll('tr')).indexOf(row);
      rows.forEach((candidate) => {
        const candidateSlide = Number(candidate.Slide);
        if (Number.isInteger(candidateSlide) && candidateSlide > currentSlide) candidate.Slide = String(candidateSlide + 1);
      });
      rows.splice(rowIndex + 1, 0, {Slide: String(currentSlide + 1)});
      renderCatalogueRows(rows);
      return;
    }
    if (action === 'up' && row.previousElementSibling) {
      body.insertBefore(row, row.previousElementSibling);
    } else if (action === 'down' && row.nextElementSibling) {
      body.insertBefore(row.nextElementSibling, row);
    } else if (action === 'delete') {
      if (activeCell?.closest('tr') === row) {
        activeCell.classList.remove('is-selected');
        activeCell = null;
        heading.textContent = 'Select a cell';
        copy.textContent = 'Select a table cell to see compatible layouts, chart types or processed CDR columns.';
        optionsLabel.hidden = true;
        apply.hidden = true;
        if (filterBuilder) filterBuilder.hidden = true;
      }
      row.remove();
    }
    normaliseCatalogueRows();
  });
  normaliseCatalogueRows();
  reenumerate?.addEventListener('click', () => {
    const body = table.querySelector('tbody');
    if (!body) return;
    const rows = Array.from(body.querySelectorAll('tr')).map((row, position) => {
      const value = rowValue(row, 'Slide');
      const parsed = Number(value);
      return {
        row,
        position,
        slide: Number.isInteger(parsed) && parsed > 0 ? parsed : null,
      };
    });
    rows.sort((left, right) => {
      if (left.slide === null && right.slide === null) return left.position - right.position;
      if (left.slide === null) return 1;
      if (right.slide === null) return -1;
      return left.slide - right.slide || left.position - right.position;
    });
    const reenumeratedSlides = new Map();
    let nextSlide = 1;
    rows.forEach(({ row, slide }) => {
      body.append(row);
      if (slide === null) return;
      if (!reenumeratedSlides.has(slide)) {
        reenumeratedSlides.set(slide, nextSlide);
        nextSlide += 1;
      }
      const reenumerated = String(reenumeratedSlides.get(slide));
      row.dataset[sharedValueKey('Slide')] = reenumerated;
      const slideCell = row.querySelector('[data-catalogue-field="Slide"]');
      if (slideCell) slideCell.textContent = reenumerated;
    });
    normaliseCatalogueRows();
  });
  table.addEventListener('focusin', (event) => {
    const cell = selectedCellFromEvent(event);
    if (cell) selectCell(cell);
  });
  table.addEventListener('click', (event) => {
    const cell = selectedCellFromEvent(event);
    if (cell) selectCell(cell);
  });
  document.addEventListener('pointerdown', (event) => {
    if (!selectedCellFromEvent(event) && !helper.contains(event.target)) hideCellAssistance();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || helper.hidden) return;
    event.preventDefault();
    hideCellAssistance();
    activeCell?.blur();
  });
  table.closest('.table-wrap')?.addEventListener('scroll', hideCellAssistance, {passive: true});
  helperClose?.addEventListener('click', hideCellAssistance);
  helper.addEventListener('focusin', (event) => window.requestAnimationFrame(() => placeAssistanceMenu(event.target)));
  helper.addEventListener('click', (event) => window.requestAnimationFrame(() => placeAssistanceMenu(event.target)));
  table.addEventListener('focusout', (event) => {
    if (event.target.closest?.('[data-catalogue-field="CDR source"]')) normaliseCatalogueRows();
    window.requestAnimationFrame(() => {
      const focused = document.activeElement;
      if (!focused?.closest?.('[data-catalogue-field]') && !helper.contains(focused)) hideCellAssistance();
    });
  });
  addFilter?.addEventListener('click', () => addFilterCondition());
  const displayChartType = (value) => String(value || '').replace(/\b\w+/g, (word) => (
    word.toLocaleLowerCase() === 'cdf'
      ? 'CDF' : `${word.charAt(0).toLocaleUpperCase()}${word.slice(1).toLocaleLowerCase()}`
  ));
  apply.addEventListener('click', () => {
    if (!activeCell) return;
    const selected = Array.from(options.selectedOptions).map((option) => option.value).filter(Boolean);
    if (!selected.length) return;
    const field = activeCell.dataset.catalogueField || '';
    const current = activeCell.textContent.trim();
    if (field === 'Layout' || field === 'CDR source' || field === 'KPI' || field === 'Legend Position') {
      activeCell.textContent = selected[0];
    } else if (field === 'Chart type') {
      activeCell.textContent = displayChartType(selected[0]);
    } else if (field === 'Filters') {
      const clauses = selected.map((value) => `${value} = `).join('; ');
      activeCell.textContent = current ? `${current}; ${clauses}` : clauses;
    } else if (field === 'Legend') {
      activeCell.textContent = selected.join(', ');
    } else {
      const currentOrder = current.split(/(?:\s*×\s*|\s+[xX]\s+)/).map((value) => value.trim()).filter(Boolean);
      const retained = currentOrder.filter((value) => selected.includes(value));
      const additions = selected.filter((value) => !currentOrder.includes(value));
      activeCell.textContent = [...retained, ...additions].join(' × ');
    }
    activeCell.focus();
  });
  const saveCatalogueTemplate = async () => {
    contentField.value = serialiseCatalogueContent();
    const saveButton = saveForm.querySelector('button[type="submit"]');
    hideCellAssistance();
    if (saveButton) saveButton.disabled = true;
    showLoadingOverlay('Saving Slides Template', 'Please wait while the Slides Template is being saved.');
    try {
      const response = await fetch(saveForm.action, {
        method: 'POST',
        body: new FormData(saveForm),
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to save the Slides Template.');
      savedCatalogueContent = contentField.value;
      hideLoadingOverlay();
      showInfoDialog(`Slides Template '${payload.template || 'selected template'}' has been saved.`, {
        title: 'Slides Template saved',
      });
      return true;
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'Unable to save the Slides Template.', {
        title: 'Slides Template save failed',
        tone: 'error',
      });
      return false;
    } finally {
      hideLoadingOverlay();
      if (saveButton) saveButton.disabled = false;
    }
  };
  // Expose the editor's current state to the template picker without storing
  // unsaved table data in the browser. The CSV rendered by the server remains
  // the single source of truth after a selection change.
  editor.hasUnsavedCatalogueChanges = hasUnsavedCatalogueChanges;
  editor.saveCatalogueTemplate = saveCatalogueTemplate;
  saveForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    await saveCatalogueTemplate();
  });
  savedCatalogueContent = serialiseCatalogueContent();
});

document.querySelectorAll('[data-catalogue-auto-rename]').forEach((input) => {
  let savedValue = input.value.trim();
  const updateCatalogueIdentifier = (previousIdentifier, identifier) => {
    if (!previousIdentifier || !identifier || previousIdentifier === identifier) return;
    const row = input.closest('tr');
    const technology = input.form?.action.match(/\/admin\/report-templates\/([^/]+)\//)?.[1];
    if (!row || !technology) return;
    const previousName = decodeURIComponent(previousIdentifier);
    const oldSegment = `/admin/report-templates/${technology}/${encodeURIComponent(previousName)}/`;
    const newSegment = `/admin/report-templates/${technology}/${encodeURIComponent(identifier)}/`;
    const rawOldSegment = `/admin/report-templates/${technology}/${previousName}/`;
    const rawNewSegment = `/admin/report-templates/${technology}/${identifier}/`;
    row.querySelectorAll('form[action], a[href]').forEach((element) => {
      const attribute = element.tagName === 'A' ? 'href' : 'action';
      const value = element.getAttribute(attribute);
      if (value?.includes(rawOldSegment)) element.setAttribute(attribute, value.replace(rawOldSegment, rawNewSegment));
      else if (value?.includes(oldSegment)) element.setAttribute(attribute, value.replace(oldSegment, newSegment));
    });
    document.querySelectorAll('option').forEach((option) => {
      if (option.value !== `${technology}:${previousName}`) return;
      option.value = `${technology}:${identifier}`;
      option.textContent = option.textContent.replace(previousName, identifier);
    });
    const parameters = new URLSearchParams(window.location.search);
    if (parameters.get('catalogue_technology') === technology && parameters.get('catalogue_id') === previousName) {
      parameters.set('catalogue_id', identifier);
      const query = parameters.toString();
      window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
    }
  };
  input.addEventListener('change', async () => {
    const name = input.value.trim();
    if (!name || name === savedValue || !input.form) return;
    const formData = new FormData(input.form);
    input.disabled = true;
    try {
      const response = await fetch(input.form.action, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'The template name could not be saved.');
      savedValue = String(payload.name || name).trim();
      input.value = savedValue;
      input.setAttribute('aria-label', `Name for ${savedValue}`);
      const previousIdentifier = input.form.action.match(/\/admin\/report-templates\/[^/]+\/([^/]+)\/rename$/)?.[1];
      updateCatalogueIdentifier(previousIdentifier, payload.identifier);
    } catch (error) {
      input.value = savedValue;
      showInfoDialog(error instanceof Error ? error.message : 'The template name could not be saved.', {
        title: 'Template Rename Failed',
      });
    } finally {
      input.disabled = false;
    }
  });
});

document.querySelectorAll('.catalogue-editor-picker-form').forEach((form) => {
  // The server-selected template is authoritative. Browsers can restore a
  // stale select value after navigation, making the picker claim that a
  // different template is open from the one rendered in the editor table.
  form.querySelectorAll('select[data-no-persist]').forEach((select) => {
    Array.from(select.options).forEach((option) => { option.selected = option.defaultSelected; });
  });
  const picker = form.querySelector('select[name="catalogue_selection"]');
  let selectedTemplate = picker?.value || '';
  picker?.addEventListener('change', async () => {
    const nextTemplate = picker.value;
    if (!nextTemplate || nextTemplate === selectedTemplate) return;
    const editor = document.querySelector('[data-catalogue-editor]');
    if (editor?.hasUnsavedCatalogueChanges?.()) {
      const saveChanges = await showConfirmDialog(
        'This template has unsaved changes. Save them before opening the selected template?',
        {title: 'Unsaved Slides Template changes', confirmLabel: 'Save changes', cancelLabel: 'Discard changes'},
      );
      if (saveChanges) {
        const saved = await editor.saveCatalogueTemplate?.();
        if (!saved) {
          picker.value = selectedTemplate;
          return;
        }
      }
    }
    selectedTemplate = nextTemplate;
    preserveAdminScrollPosition();
    form.submit();
  });
  form.addEventListener('submit', () => preserveAdminScrollPosition());
});

document.querySelectorAll('form[action*="/admin/report-templates/"]').forEach((form) => {
  if (form.classList.contains('catalogue-rename-form')) return;
  form.addEventListener('submit', () => preserveAdminScrollPosition());
});

document.querySelectorAll('[data-catalogue-import-form]').forEach((form) => {
  const name = form.querySelector('[data-catalogue-import-name]');
  const file = form.querySelector('[data-catalogue-import-file]');
  const convert = form.querySelector('[data-catalogue-convert]');
  const overwrite = form.querySelector('[data-catalogue-overwrite]');
  let templateLibrary = {};
  try { templateLibrary = JSON.parse(form.dataset.catalogueTemplateLibrary || '{}'); } catch (_error) { templateLibrary = {}; }
  const currentHeaders = [
    'Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout', 'Chart Tittle', 'CDR source',
    'KPI', 'Chart type', 'Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend', 'Legend Position',
  ];
  const normalizedHeader = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const hasCurrentSchema = async (selected) => {
    const headerLine = (await selected.slice(0, 65536).text())
      .replace(/^\uFEFF/, '')
      .split(/\r?\n/)
      .find((line) => line.trim());
    if (!headerLine) return false;
    const headers = headerLine.split(',').map((header) => normalizedHeader(header.replace(/^"|"$/g, '')));
    return headers.length === currentHeaders.length
      && headers.every((header, index) => header === normalizedHeader(currentHeaders[index]));
  };
  file?.addEventListener('change', () => {
    const selected = file.files?.[0];
    if (!selected || !name || name.value.trim()) return;
    name.value = selected.name.replace(/\.csv$/i, '').replace(/_+/g, ' ').trim();
  });
  form.addEventListener('submit', async (event) => {
    if (form.dataset.catalogueSubmitting === '1') return;
    event.preventDefault();
    const selected = file?.files?.[0];
    if (!selected) {
      preserveAdminScrollPosition();
      form.dataset.catalogueSubmitting = '1';
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    let shouldConvert = false;
    try {
      shouldConvert = !(await hasCurrentSchema(selected));
    } catch (_) {
      // Let the server provide the detailed error if this file cannot be read.
    }
    if (shouldConvert) {
      const accepted = await showConfirmDialog(
        'This CSV uses an older or different column layout. Compatible fields will be migrated to the current Slides Templates format; new presentation fields will be left blank where they do not exist.',
        {title: 'Convert Slides Templates?', confirmLabel: 'Convert and Import'},
      );
      if (!accepted) return;
    }
    const templateType = form.querySelector('[name="template_type"]')?.value?.trim().toLocaleLowerCase() || 'nsa';
    const requestedName = (name?.value?.trim() || selected.name.replace(/\.csv$/i, '').replace(/_+/g, ' ').trim());
    const existing = (templateLibrary?.[templateType] || []).find((templateName) => (
      String(templateName || '').trim().toLocaleLowerCase() === requestedName.toLocaleLowerCase()
    ));
    if (existing) {
      const accepted = await showConfirmDialog(
        `A ${templateType.toUpperCase()} template named '${existing}' already exists. Do you want to overwrite it?`,
        {title: 'Overwrite Slides Template?', confirmLabel: 'Overwrite template'},
      );
      if (!accepted) return;
    }
    if (convert) convert.value = shouldConvert ? '1' : '0';
    if (overwrite) overwrite.value = existing ? '1' : '0';
    form.dataset.catalogueSubmitting = '1';
    showLoadingOverlay('Importing Slides Templates', 'Validating and storing the selected template in the workspace.');
    preserveAdminScrollPosition();
    HTMLFormElement.prototype.submit.call(form);
  });
});

document.addEventListener('click', (event) => {
  const previewLink = event.target.closest('[data-preview-open-link]');
  if (previewLink) {
    if (previewLink.target === '_blank') return;
    showLoadingOverlay(previewLink.dataset.loadingLabel || 'Generating dataset preview');
    return;
  }
  const openLink = event.target.closest('[data-dashboard-open-link]');
  if (!openLink) return;
  const datasetId = openLink.dataset.datasetId;
  if (!datasetId) return;
  event.preventDefault();
  navigateToPersistedDatasetDashboard(
    datasetId,
    openLink.dataset.inputKind,
    openLink.dataset.loadingLabel || 'Opening dataset dashboard',
  );
});

document.querySelectorAll('.collapsible-panel').forEach((panel) => {
  const chip = panel.querySelector('.collapse-chip');
  const updateChip = () => {
    if (!chip) return;
    chip.textContent = panel.open ? 'Collapse' : 'Expand';
  };
  updateChip();
  panel.addEventListener('toggle', updateChip);
});

(() => {
  const workspaceSwitchers = document.querySelectorAll('.topnav-workspace-switcher');
  if (!workspaceSwitchers.length) return;
  document.addEventListener('click', (event) => {
    workspaceSwitchers.forEach((switcher) => {
      if (switcher.open && !switcher.contains(event.target)) switcher.open = false;
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    workspaceSwitchers.forEach((switcher) => { switcher.open = false; });
  });
})();

const loadingOverlay = document.getElementById('loading-overlay');
const loadingTitle = document.getElementById('loading-title');
const loadingCopy = document.getElementById('loading-copy');
const loadingProgressBar = document.querySelector('.loading-progress-bar');
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmTitle = document.getElementById('confirm-title');
const confirmCopy = document.getElementById('confirm-copy');
const confirmOption = document.getElementById('confirm-option');
const confirmOptionInput = document.getElementById('confirm-option-input');
const confirmOptionLabel = document.getElementById('confirm-option-label');
const confirmAccept = document.getElementById('confirm-accept');
const confirmCancel = document.getElementById('confirm-cancel');
const catalogueInsertOverlay = document.getElementById('catalogue-insert-overlay');
const catalogueInsertTitle = document.getElementById('catalogue-insert-title');
const catalogueInsertCopy = document.getElementById('catalogue-insert-copy');
const catalogueInsertChart = document.getElementById('catalogue-insert-chart');
const catalogueInsertSlide = document.getElementById('catalogue-insert-slide');
const catalogueInsertCancel = document.getElementById('catalogue-insert-cancel');
const infoOverlay = document.getElementById('info-overlay');
const infoTitle = document.getElementById('info-title');
const infoCopy = document.getElementById('info-copy');
const infoClose = document.getElementById('info-close');
const infoEyebrow = document.getElementById('info-eyebrow');
const infoIcon = document.getElementById('info-icon');
const filePickerInput = document.querySelector('[data-file-picker-input]');
const filePickerText = document.querySelector('[data-file-picker-text]');
const inputKindSelect = document.querySelector('[data-input-kind-select]');
const datasetSelect = document.querySelector('[data-dataset-select]');
const logTypeFilter = document.querySelector('[data-log-type-filter]');
const persistencePathnames = new Set(['/dashboard', '/admin']);
const dashboardStateKey = 'dashboard-analytic:/dashboard:last-query';
const dashboardStateKeyPrefix = 'dashboard-analytic:/dashboard:last-query:dataset:';
const activeDatasetStateKey = 'dashboard-analytic:active-dataset';
const adminScrollRestoreKey = 'dashboard-analytic:/admin:scroll-restore';
let hasPendingLocationRestore = false;

function preserveAdminScrollPosition() {
  if (window.location.pathname !== '/admin') return;
  try {
    window.sessionStorage.setItem(adminScrollRestoreKey, String(window.scrollY));
  } catch (_error) {
    // A blocked storage area only affects the convenience restoration.
  }
}

function restoreAdminScrollPosition() {
  if (window.location.pathname !== '/admin') return;
  try {
    const value = window.sessionStorage.getItem(adminScrollRestoreKey);
    if (value === null) return;
    window.sessionStorage.removeItem(adminScrollRestoreKey);
    const top = Number(value);
    if (Number.isFinite(top) && top > 0) {
      requestAnimationFrame(() => window.scrollTo({top, behavior: 'auto'}));
    }
  } catch (_error) {
    // A blocked storage area only affects the convenience restoration.
  }
}

restoreAdminScrollPosition();

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

function buildDatasetDashboardUrl(params) {
  const persistedDashboardQuery = getPersistedDashboardQuery(params);
  if (persistedDashboardQuery) {
    return buildRestoredDashboardUrl(params, persistedDashboardQuery);
  }
  const query = params.toString();
  return query ? `/dashboard?${query}` : '/dashboard';
}

function navigateToPersistedDatasetDashboard(datasetId, inputKind, loadingLabel = 'Opening dataset dashboard') {
  const params = new URLSearchParams();
  const normalizedDatasetId = String(datasetId || '').trim();
  const normalizedInputKind = String(inputKind || '').trim();
  if (!normalizedDatasetId) return false;
  params.set('dataset_id', normalizedDatasetId);
  if (normalizedInputKind) {
    params.set('input_kind', normalizedInputKind);
  }
  showLoadingOverlay(loadingLabel);
  replaceLocation(buildDatasetDashboardUrl(params));
  return true;
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
  if (control.hasAttribute('data-no-persist')) return false;
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

function setupSearchableSingleSelects() {
  document.querySelectorAll('select[data-searchable-select]:not([multiple])').forEach((select) => {
    if (select.dataset.searchableReady === '1') return;
    select.dataset.searchableReady = '1';
    select.classList.add('searchable-select-native');

    const shell = document.createElement('div');
    shell.className = 'searchable-select-shell';
    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'searchable-select-input';
    input.placeholder = 'Search values…';
    input.setAttribute('aria-label', select.getAttribute('aria-label') || 'Search values');
    const menu = document.createElement('div');
    menu.className = 'searchable-select-menu';
    menu.hidden = true;

    const syncInput = () => {
      const current = Array.from(select.options).find((option) => option.selected);
      input.value = current?.textContent?.trim() || '';
    };
    const renderOptions = (query = '') => {
      const normalized = query.trim().toLocaleLowerCase();
      menu.replaceChildren();
      Array.from(select.options).filter((option) => (
        !option.disabled && (!normalized || (option.textContent || '').toLocaleLowerCase().includes(normalized))
      )).forEach((option) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'searchable-select-option';
        item.textContent = option.textContent || option.value;
        item.setAttribute('aria-selected', String(option.selected));
        item.addEventListener('click', () => {
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          select.dispatchEvent(new Event('input', { bubbles: true }));
          syncInput();
          menu.hidden = true;
        });
        menu.appendChild(item);
      });
      if (!menu.childElementCount) {
        const empty = document.createElement('p');
        empty.className = 'searchable-select-empty';
        empty.textContent = 'No matching values';
        menu.appendChild(empty);
      }
    };
    const filterSingleSelect = () => {
      renderOptions(input.value);
      menu.hidden = false;
    };
    input.addEventListener('focus', () => {
      // Replace the current selection when the user starts typing a search.
      input.select();
      renderOptions('');
      menu.hidden = false;
    });
    input.addEventListener('input', filterSingleSelect);
    input.addEventListener('keyup', filterSingleSelect);
    input.addEventListener('search', filterSingleSelect);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { menu.hidden = true; input.blur(); }
    });
    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) menu.hidden = true;
    });
    select.addEventListener('change', syncInput);
    const rebuildOnOptionUpdate = () => {
      select.removeEventListener('searchable-select:options-updated', rebuildOnOptionUpdate);
      shell.remove();
      select.classList.remove('searchable-select-native');
      delete select.dataset.searchableReady;
    };
    select.addEventListener('searchable-select:options-updated', rebuildOnOptionUpdate);
    select.after(shell);
    shell.append(input, menu);
    syncInput();
  });
}

function setupWorkspaceUserPickers() {
  document.querySelectorAll('[data-workspace-user-picker]').forEach((picker) => {
    if (picker.dataset.workspaceUserPickerReady === '1') return;
    picker.dataset.workspaceUserPickerReady = '1';
    const search = picker.querySelector('.workspace-user-picker-search');
    const toggle = picker.querySelector('.workspace-user-picker-toggle');
    const menu = picker.querySelector('.workspace-user-picker-menu');
    const options = Array.from(picker.querySelectorAll('.workspace-user-picker-menu label'));
    const checkboxes = options.map((option) => option.querySelector('input[type="checkbox"]')).filter((checkbox) => checkbox && !checkbox.disabled);
    const portalize = Boolean(picker.closest('.table-wrap')) && Boolean(menu);
    const menuHome = menu?.parentNode;
    const menuNextSibling = menu?.nextSibling;

    const positionPortalMenu = () => {
      if (!portalize || !menu || !picker.open) return;
      const bounds = picker.getBoundingClientRect();
      const availableHeight = Math.max(8 * 16, window.innerHeight - bounds.bottom - 16);
      Object.assign(menu.style, {
        left: `${Math.max(8, bounds.left)}px`,
        top: `${bounds.bottom - 1}px`,
        width: `${Math.max(bounds.width, 184)}px`,
        maxHeight: `${Math.min(224, availableHeight)}px`,
      });
    };
    const restorePortalMenu = () => {
      if (!portalize || !menu || !menuHome || !menu.classList.contains('workspace-user-picker-menu-portal')) return;
      menuHome.insertBefore(menu, menuNextSibling);
      menu.classList.remove('workspace-user-picker-menu-portal');
      menu.removeAttribute('style');
    };

    const filter = () => {
      const query = (search?.value || '').trim().toLocaleLowerCase();
      options.forEach((option) => {
        option.hidden = Boolean(query) && !option.textContent.toLocaleLowerCase().includes(query);
      });
    };
    search?.addEventListener('input', filter);
    search?.addEventListener('keyup', filter);
    search?.addEventListener('search', filter);
    toggle?.addEventListener('click', () => {
      const shouldSelectAll = checkboxes.some((checkbox) => !checkbox.checked);
      checkboxes.forEach((checkbox) => { checkbox.checked = shouldSelectAll; });
      filter();
    });
    picker.addEventListener('toggle', () => {
      const parentPanel = picker.closest('.collapsible-panel');
      if (parentPanel) {
        parentPanel.classList.toggle(
          'workspace-user-picker-open',
          Boolean(parentPanel.querySelector('.workspace-user-picker[open]')),
        );
      }
      if (picker.open && search) {
        if (portalize && menu) {
          menu.classList.add('workspace-user-picker-menu-portal');
          document.body.append(menu);
          positionPortalMenu();
        }
        search.value = '';
        filter();
        window.setTimeout(() => search.focus(), 0);
      } else {
        restorePortalMenu();
      }
    });
    document.addEventListener('click', (event) => {
      const clickInPortalMenu = Boolean(menu?.classList.contains('workspace-user-picker-menu-portal') && menu.contains(event.target));
      if (picker.open && !picker.contains(event.target) && !clickInPortalMenu) {
        picker.open = false;
      }
    });
    window.addEventListener('resize', positionPortalMenu);
    document.addEventListener('scroll', positionPortalMenu, true);
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

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'multiselect-search';
    search.placeholder = 'Filter values…';
    search.setAttribute('aria-label', 'Filter available values');
    menu.appendChild(search);

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.className = 'multiselect-action';
    if (select.closest('.reporting-stack')) {
      // Reporting has its own button palette.  Mark this generated control so
      // it cannot inherit the strong primary-reporting button treatment.
      actionButton.classList.add('reporting-multiselect-action');
    }
    actionButton.textContent = 'Select All / None';
    menu.appendChild(actionButton);

    const syncTrigger = () => {
      const enabledOptions = Array.from(select.options).filter((option) => !option.disabled);
      const selectedOptions = enabledOptions.filter((option) => option.selected).map((option) => option.textContent?.trim()).filter(Boolean);
      const totalEnabled = enabledOptions.length;
      if (totalEnabled === 0) {
        triggerLabel.textContent = 'No values';
      } else if (selectedOptions.length === 0) {
        triggerLabel.textContent = 'None Selected';
      } else if (selectedOptions.length === 1) {
        // A one-item Reporting source selector is already fully selected, but
        // its file name is more useful than the generic "All values" summary.
        triggerLabel.textContent = selectedOptions[0];
      } else if (totalEnabled > 0 && selectedOptions.length === totalEnabled) {
        triggerLabel.textContent = 'All values';
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
      menu.hidden = true;
      syncTrigger();
      trigger.focus();
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

    const filterMultiSelect = () => {
      const query = search.value.trim().toLocaleLowerCase();
      Array.from(menu.querySelectorAll('.multiselect-option')).forEach((optionLabel) => {
        const text = optionLabel.textContent?.toLocaleLowerCase() || '';
        optionLabel.hidden = Boolean(query) && !text.includes(query);
      });
    };
    search.addEventListener('input', filterMultiSelect);
    search.addEventListener('keyup', filterMultiSelect);
    search.addEventListener('search', filterMultiSelect);

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
      if (!menu.hidden) search.focus();
    });

    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) {
        menu.hidden = true;
        syncTrigger();
      }
    });

    select.addEventListener('change', syncCheckboxes);
    const rebuildOnOptionUpdate = () => {
      // Dynamic option lists need a new checkbox menu to remain in sync.
      select.removeEventListener('multiselect:options-updated', rebuildOnOptionUpdate);
      shell.remove();
      select.classList.remove('multiselect-native');
      delete select.dataset.multiselectReady;
      setupCustomMultiSelects();
    };
    select.addEventListener('multiselect:options-updated', rebuildOnOptionUpdate);
    select.after(shell);
    shell.appendChild(trigger);
    shell.appendChild(menu);
    syncCheckboxes();
  });
}

// The Chart Viewer and the Slides Template editor deliberately share this
// control surface. Keeping the filter builder and the searchable popovers in
// one component prevents the two previews from drifting apart.
function createInteractiveChartPreviewControls(fieldsElement, definition, options = {}) {
  if (!fieldsElement) return {definition: () => ({})};
  const fields = options.fields || [
    ['chart_type', 'Chart Type'], ['cdr_source', 'CDR Source'], ['kpi', 'KPI'], ['filters', 'Filters'],
    ['grouping_rows', 'Rows'], ['grouping_columns', 'Columns'], ['legend', 'Legend'], ['legend_position', 'Legend Position'],
  ];
  const multiFields = new Set(['grouping_rows', 'grouping_columns', 'legend']);
  const sourceKey = (source) => {
    const normalized = String(source || '').trim().toLowerCase();
    return ({data: 'cdr-data', voice: 'cdr-voice', speech: 'cdr-speech'})[normalized] || (normalized.startsWith('cdr-') ? normalized : `cdr-${normalized}`);
  };
  const columnsFor = (source) => Array.from(new Set((options.columnsBySource || {})[sourceKey(source)] || [])).sort((left, right) => left.localeCompare(right));
  const valuesFor = (value, key) => new Set(String(value || '').split(key === 'legend' ? ',' : /\s*(?:×|x)\s*/i).map((item) => item.trim()).filter(Boolean));
  const normalisePreviewValue = (value) => String(value || '').trim().toLocaleLowerCase().replace(/[^a-z0-9]+/g, '');
  const matchingPreviewValue = (requested, available) => (
    available.find((value) => normalisePreviewValue(value) === normalisePreviewValue(requested)) || requested
  );
  const orderedSelectedValues = (select) => {
    const selected = new Set(Array.from(select.selectedOptions).map((option) => option.value));
    let order = [];
    try { order = JSON.parse(select.dataset.previewSelectionOrder || '[]'); } catch (_error) { order = []; }
    order = order.filter((value) => selected.has(value));
    Array.from(selected).forEach((value) => { if (!order.includes(value)) order.push(value); });
    select.dataset.previewSelectionOrder = JSON.stringify(order);
    return order;
  };
  const currentDefinition = () => Object.fromEntries(Array.from(fieldsElement.querySelectorAll('[name]')).map((control) => {
    if (!control.multiple) return [control.name, control.value];
    return [control.name, orderedSelectedValues(control).join(control.name === 'legend' ? ', ' : ' × ')];
  }));
  let activeMenu = null;
  let activeMenuTrigger = null;
  let activeMenuHome = null;
  let activeMenuNextSibling = null;
  let closeTimer = null;
  const closeMenu = () => {
    if (closeTimer) window.clearTimeout(closeTimer);
    closeTimer = null;
    activeMenuTrigger?.setAttribute('aria-expanded', 'false');
    activeMenu?.setAttribute('hidden', '');
    if (activeMenu && activeMenuHome) activeMenuHome.insertBefore(activeMenu, activeMenuNextSibling);
    activeMenu = null; activeMenuTrigger = null; activeMenuHome = null; activeMenuNextSibling = null;
  };
  const setupSelects = () => {
    // Filter-condition selects are dynamic and do not have a name. Include
    // them explicitly so Column and Operator receive the same searchable,
    // single-value dropdown used by KPI and CDR Source in every preview host.
    fieldsElement.querySelectorAll('select[name], select[data-report-chart-filter-select], .report-chart-filter-condition select').forEach((select) => {
      const shell = document.createElement('div'); shell.className = 'report-chart-preview-select';
      const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'report-chart-preview-select-trigger'; trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');
      const triggerText = document.createElement('span'); triggerText.className = 'report-chart-preview-select-value'; trigger.append(triggerText);
      const menu = document.createElement('div'); menu.className = 'report-chart-preview-select-menu'; menu.hidden = true;
      const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search values…'; search.setAttribute('aria-label', `Search ${select.getAttribute('aria-label') || 'values'}`);
      const menuOptions = document.createElement('div'); menuOptions.className = 'report-chart-preview-select-options';
      const syncTrigger = () => {
        const selected = Array.from(select.selectedOptions).map((option) => option.textContent?.trim()).filter(Boolean);
        const configured = select.dataset.previewDisplay || '';
        triggerText.textContent = select.multiple
          ? (selected.length ? `${selected.length} selected` : (configured ? `${configured.split(select.name === 'legend' ? ',' : /\s*(?:×|x)\s*/i).filter(Boolean).length} selected` : 'Select fields…'))
          : (selected[0] || configured || 'Select a value…');
      };
      const renderOptions = () => {
        const query = search.value.trim().toLocaleLowerCase();
        menuOptions.replaceChildren(...Array.from(select.options).filter((option) => !option.disabled && (!query || option.textContent.toLocaleLowerCase().includes(query))).map((option) => {
          if (select.multiple) {
            const item = document.createElement('label'); item.className = 'report-chart-preview-select-option is-multiple';
            const input = document.createElement('input'); input.type = 'checkbox'; input.checked = option.selected;
            const text = document.createElement('span'); text.textContent = option.textContent;
            input.addEventListener('change', () => { option.selected = input.checked; let order = orderedSelectedValues(select); order = input.checked ? [...order.filter((value) => value !== option.value), option.value] : order.filter((value) => value !== option.value); select.dataset.previewSelectionOrder = JSON.stringify(order); select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); });
            item.append(input, text); return item;
          }
          const item = document.createElement('button'); item.type = 'button'; item.className = 'report-chart-preview-select-option'; item.textContent = option.textContent; item.setAttribute('aria-selected', String(option.selected));
          item.addEventListener('click', () => { select.value = option.value; select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); closeMenu(); });
          return item;
        }));
        if (!menuOptions.childElementCount) { const empty = document.createElement('p'); empty.className = 'report-chart-preview-select-empty'; empty.textContent = 'No matching values'; menuOptions.append(empty); }
      };
      if (select.multiple) {
        const actions = document.createElement('div'); actions.className = 'report-chart-preview-select-actions';
        const toggleAll = document.createElement('button'); toggleAll.type = 'button'; toggleAll.textContent = 'Select all / none';
        toggleAll.addEventListener('click', () => { const selectable = Array.from(select.options).filter((option) => !option.disabled); const selectAll = selectable.some((option) => !option.selected); selectable.forEach((option) => { option.selected = selectAll; }); select.dataset.previewSelectionOrder = JSON.stringify(selectAll ? selectable.map((option) => option.value) : []); select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); renderOptions(); });
        actions.append(toggleAll); menu.append(search, actions, menuOptions);
      } else menu.append(search, menuOptions);
      search.addEventListener('input', renderOptions);
      const toggleMenu = () => {
        if (activeMenu === menu) { closeMenu(); return; }
        closeMenu(); renderOptions();
        // Some hosts use a backdrop that creates a new fixed-positioning
        // context. Each caller can therefore choose the visible dialog layer
        // that owns its popup; the template editor deliberately uses body.
        activeMenuHome = menu.parentNode;
        activeMenuNextSibling = menu.nextSibling;
        (options.menuContainer || document.body).append(menu);
        menu.hidden = false; activeMenu = menu; activeMenuTrigger = trigger; trigger.setAttribute('aria-expanded', 'true');
        const bounds = trigger.getBoundingClientRect(); menu.style.left = `${Math.max(8, Math.min(bounds.left, window.innerWidth - 380))}px`; menu.style.top = `${Math.min(bounds.bottom + 4, window.innerHeight - 310)}px`; search.focus();
      };
      trigger.addEventListener('click', toggleMenu);
      trigger.addEventListener('keydown', (event) => { if (['Enter', ' ', 'ArrowDown'].includes(event.key)) { event.preventDefault(); toggleMenu(); } });
      shell.addEventListener('mouseenter', () => { if (closeTimer) window.clearTimeout(closeTimer); });
      shell.addEventListener('mouseleave', () => { if (closeTimer) window.clearTimeout(closeTimer); closeTimer = window.setTimeout(() => { if (activeMenu === menu) closeMenu(); }, 550); });
      menu.addEventListener('mouseenter', () => { if (closeTimer) window.clearTimeout(closeTimer); });
      menu.addEventListener('mouseleave', () => { if (closeTimer) window.clearTimeout(closeTimer); closeTimer = window.setTimeout(() => { if (activeMenu === menu) closeMenu(); }, 550); });
      select.classList.add('report-chart-preview-select-native'); select.after(shell); shell.append(trigger, menu); syncTrigger();
    });
  };
  document.addEventListener('click', (event) => {
    if (activeMenu && !activeMenu.contains(event.target) && !activeMenuTrigger?.closest('.report-chart-preview-select')?.contains(event.target)) closeMenu();
  });
  fieldsElement.replaceChildren(...fields.map(([key, label]) => {
    const field = document.createElement('label'); field.dataset.previewField = key; field.textContent = label;
    if (options.textFields?.[key]) {
      const control = document.createElement('input');
      control.type = 'text'; control.name = key; control.value = definition[key] || ''; control.setAttribute('aria-label', label);
      field.append(control); return field;
    }
    if (key === 'filters') {
      const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = 'filters';
      const builder = document.createElement('div'); builder.className = 'report-chart-filter-builder';
      const conditions = document.createElement('div'); conditions.className = 'report-chart-filter-conditions';
      const parsedField = document.createElement('input'); parsedField.type = 'text'; parsedField.className = 'report-chart-preview-parsed'; parsedField.readOnly = true; parsedField.placeholder = 'Parsed filter'; parsedField.setAttribute('aria-label', 'Parsed filter');
      const sync = () => { hidden.value = Array.from(conditions.children).map((row) => { const [column, operator] = row.querySelectorAll('select'); const value = row.querySelector('[data-report-chart-filter-value]'); const rawValue = value?.value.trim(); const parserValue = ['IN', 'NOT IN'].includes(operator?.value) && rawValue && !/^\(.*\)$/.test(rawValue) ? `(${rawValue})` : rawValue; return column?.value && operator?.value && parserValue ? `${column.value} ${operator.value} ${parserValue}` : ''; }).filter(Boolean).join('; '); parsedField.value = hidden.value; hidden.dispatchEvent(new Event('input')); };
      const addCondition = (condition = {}) => {
        const row = document.createElement('div'); row.className = 'report-chart-filter-condition';
        const column = document.createElement('select'); column.add(new Option('Column…', '')); column.dataset.reportChartFilterSelect = ''; column.setAttribute('aria-label', 'Filter column');
        const filterColumns = Array.from(new Set([condition.column || '', ...columnsFor(definition.cdr_source)].filter(Boolean)));
        const selectedColumn = matchingPreviewValue(condition.column, filterColumns);
        filterColumns.forEach((value) => column.add(new Option(value, value, false, value === selectedColumn)));
        const operator = document.createElement('select'); operator.dataset.reportChartFilterSelect = ''; operator.setAttribute('aria-label', 'Filter operator'); ['=', '!=', 'CONTAINS', 'NOT CONTAINS', 'IN', 'NOT IN', '>=', '<=', '>', '<'].forEach((value) => operator.add(new Option(value, value, false, value === condition.operator)));
        const value = document.createElement('input'); value.type = 'text'; value.dataset.reportChartFilterValue = ''; value.placeholder = 'Value'; value.value = condition.value || '';
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '−'; remove.title = 'Remove condition'; remove.addEventListener('click', () => { row.remove(); sync(); });
        [column, operator, value].forEach((input) => { input.addEventListener('input', sync); input.addEventListener('change', sync); }); row.append(column, operator, value, remove); conditions.append(row);
      };
      const parsed = String(definition.filters || '').split(';').map((item) => item.trim()).filter(Boolean).map((item) => { const match = item.match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i); return match ? {column: match[1].trim(), operator: match[2].toUpperCase(), value: match[3].trim()} : {}; });
      (parsed.length ? parsed : [{}]).forEach(addCondition);
      const add = document.createElement('button'); add.type = 'button'; add.className = 'report-chart-filter-add'; add.textContent = '+ Add condition'; add.addEventListener('click', () => addCondition());
      builder.append(conditions, add); field.append(hidden, builder, parsedField); sync(); return field;
    }
    const control = document.createElement('select');
    if (key === 'chart_type') (options.chartTypes || []).forEach((value) => control.add(new Option(value, value, false, normalisePreviewValue(value) === normalisePreviewValue(definition[key]))));
    else if (key === 'cdr_source') (options.cdrSources || ['CDR-Data', 'CDR-Voice', 'CDR-Speech']).forEach((value) => control.add(new Option(value, value, false, sourceKey(value) === sourceKey(definition[key]))));
    else if (key === 'legend_position') (options.legendPositions || ['Top', 'Bottom', 'Left', 'Right']).forEach((value) => control.add(new Option(value, value, false, normalisePreviewValue(value) === normalisePreviewValue(definition[key]))));
    else {
      const available = columnsFor(definition.cdr_source);
      const selected = new Set(Array.from(valuesFor(definition[key], key)).map((value) => matchingPreviewValue(value, available)));
      if (multiFields.has(key)) control.multiple = true; else control.add(new Option('Choose a field…', ''));
      Array.from(new Set([...selected, ...available])).filter(Boolean).forEach((value) => control.add(new Option(value, value, false, selected.has(value))));
    }
    // Explicit assignment is needed after dynamic menu reconstruction: a
    // browser can otherwise retain the blank placeholder selected even when
    // the option was initially marked selected by the constructor.
    if (control.multiple) {
      const requested = valuesFor(definition[key], key);
      Array.from(control.options).forEach((option) => {
        option.selected = Array.from(requested).some((value) => normalisePreviewValue(value) === normalisePreviewValue(option.value));
      });
    } else {
      const requested = key === 'cdr_source' ? sourceKey(definition[key]) : normalisePreviewValue(definition[key]);
      const matching = Array.from(control.options).find((option) => (
        key === 'cdr_source' ? sourceKey(option.value) === requested : normalisePreviewValue(option.value) === requested
      ));
      if (matching) control.value = matching.value;
    }
    if (control.multiple) control.dataset.previewSelectionOrder = JSON.stringify(Array.from(valuesFor(definition[key], key)).map((value) => matchingPreviewValue(value, Array.from(control.options).map((option) => option.value))));
    control.name = key; control.dataset.previewDisplay = String(definition[key] || ''); control.setAttribute('aria-label', label); field.append(control);
    if (key === 'grouping_rows' || key === 'grouping_columns') {
      const parsed = document.createElement('input'); parsed.type = 'text'; parsed.className = 'report-chart-preview-parsed'; parsed.readOnly = true; parsed.placeholder = `Parsed ${label}`; parsed.setAttribute('aria-label', `Parsed ${label}`);
      const syncParsed = () => { parsed.value = orderedSelectedValues(control).join(' × '); };
      control.addEventListener('input', syncParsed); control.addEventListener('change', syncParsed); syncParsed(); field.append(parsed);
    }
    return field;
  }));
  setupSelects();
  fieldsElement.querySelector('[name="cdr_source"]')?.addEventListener('change', () => options.onSourceChange?.(currentDefinition()));
  fieldsElement.querySelectorAll('[name]').forEach((control) => control.addEventListener('input', () => options.onChange?.(currentDefinition())));
  fieldsElement.querySelectorAll('select[name]').forEach((control) => control.addEventListener('change', () => options.onChange?.(currentDefinition())));
  return {definition: currentDefinition, close: closeMenu};
}

function hideLoadingOverlay() {
  if (!loadingOverlay) return;
  loadingOverlay.hidden = true;
  document.body.classList.remove('loading-active');
}

function showLoadingOverlay(label, copy) {
  if (!loadingOverlay) return;
  loadingTitle.textContent = label || 'Processing request';
  loadingCopy.textContent = copy || 'Please wait while the workspace processes the selected dataset or updates the dashboard.';
  if (loadingProgressBar instanceof HTMLElement) {
    loadingProgressBar.style.width = '45%';
    loadingProgressBar.style.animation = '';
  }
  loadingOverlay.hidden = false;
  document.body.classList.add('loading-active');
}

function setLoadingProgress(progress) {
  if (!(loadingProgressBar instanceof HTMLElement)) return;
  const numericProgress = Number(progress);
  if (!Number.isFinite(numericProgress) || numericProgress <= 0) {
    loadingProgressBar.style.width = '45%';
    loadingProgressBar.style.animation = '';
    return;
  }
  loadingProgressBar.style.width = `${Math.min(100, Math.max(0, numericProgress))}%`;
  loadingProgressBar.style.animation = 'none';
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
  showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
  try {
    const method = String(form.method || 'post').toUpperCase();
    const formData = new FormData(form);
    const requestUrl = method === 'GET'
      ? `${form.action}${form.action.includes('?') ? '&' : '?'}${new URLSearchParams(formData).toString()}`
      : form.action;
    const response = await fetch(requestUrl, method === 'GET' ? {
      method,
      credentials: 'same-origin',
    } : {
      method,
      body: formData,
      credentials: 'same-origin',
    });
    if (!response.ok) {
      hideLoadingOverlay();
      alert(`Download failed with status ${response.status}.`);
      return;
    }
    const blob = await response.blob();
    const fallbackName = form.action.includes('/import-export/export')
      ? 'dashboard-analytic-export.zip'
      : (form.action.includes('/powerpoint') ? 'report.pptx' : 'report.docx');
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
setupWorkspaceUserPickers();
setupCustomMultiSelects();
setupSearchableSingleSelects();

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

function importWarningDetails(payload) {
  const kind = String(payload.kind || '');
  const collisions = Array.isArray(payload.workspace_collisions) ? payload.workspace_collisions : [];
  if (kind === 'config') {
    return payload.includes_slides_templates
      ? {
        title: 'Overwrite configuration and templates?',
        message: 'This will overwrite the configuration files and shared Slides Templates included in the package. The local workspace registry and existing workspaces will be preserved.',
      }
      : {
        title: 'Overwrite configuration?',
        message: 'This will overwrite the configuration files included in the package. The local workspace registry and existing workspaces will be preserved.',
      };
  }
  if (kind === 'slides-templates') {
    return {
      title: 'Overwrite Slides Templates?',
      message: 'This will overwrite the shared Slides Templates included in the package.',
    };
  }
  if (kind === 'workspace') {
    const name = collisions[0];
    return name
      ? {
        title: 'Overwrite workspace?',
        message: `Workspace "${name}" already exists and will be permanently replaced by the imported workspace.`,
      }
      : {
        title: 'Import workspace?',
        message: 'A new workspace will be created from this package.',
      };
  }
  const collisionCopy = collisions.length
    ? ` The following existing workspaces will be permanently replaced: ${collisions.join(', ')}.`
    : ' New workspaces will be created from the package.';
  return {
    title: 'Overwrite full environment?',
    message: `This will overwrite the configuration files and shared Slides Templates included in the package.${collisionCopy} The local workspace registry will be rebuilt from the imported workspaces.`,
  };
}

function formatImportUploadBytes(bytes) {
  const numeric = Number(bytes);
  if (!Number.isFinite(numeric) || numeric < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = numeric;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function uploadImportPackage(file) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/admin/import-export/inspect/upload', true);
    request.withCredentials = true;
    request.setRequestHeader('Accept', 'application/json');
    request.setRequestHeader('Content-Type', file.type || 'application/zip');
    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return;
      const progress = event.total ? (event.loaded / event.total) * 100 : 0;
      setLoadingProgress(progress);
      if (loadingCopy) {
        loadingCopy.textContent = `Uploading ${formatImportUploadBytes(event.loaded)} of ${formatImportUploadBytes(event.total)} — ${Math.round(progress)}%.`;
      }
    });
    request.addEventListener('load', () => {
      let payload = {};
      try { payload = JSON.parse(request.responseText || '{}'); } catch (_error) { /* Handled below. */ }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(payload.detail || 'The selected file is not a valid export package.'));
        return;
      }
      resolve({payload, uploadId: request.getResponseHeader('X-Import-Upload-Id')});
    });
    request.addEventListener('error', () => reject(new Error('The import package upload was interrupted.')));
    request.addEventListener('abort', () => reject(new Error('The import package upload was cancelled.')));
    request.send(file);
  });
}

document.querySelectorAll('[data-import-export-form]').forEach((form) => {
  const confirmed = form.querySelector('[data-import-export-confirmed]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!(form instanceof HTMLFormElement) || !(confirmed instanceof HTMLInputElement)) return;
    if (!form.reportValidity()) return;
    const packageInput = form.querySelector('input[type="file"][name="package"]');
    const packageFile = packageInput instanceof HTMLInputElement ? packageInput.files?.[0] : null;
    if (!packageFile) return;
    confirmed.value = '0';
    showLoadingOverlay(
      'Uploading import package',
      'Uploading the selected ZIP package for inspection. Large workspace packages can take several minutes; the import warning will appear as soon as the upload is ready.',
    );
    try {
      // Let the browser paint the progress dialog before starting a potentially large upload.
      await new Promise((resolve) => window.requestAnimationFrame(resolve));
      const {payload, uploadId} = await uploadImportPackage(packageFile);
      if (!uploadId) throw new Error('The uploaded package could not be retained for import.');
      setLoadingProgress(100);
      if (loadingCopy) loadingCopy.textContent = 'Upload complete. Inspecting the package…';
      const warning = importWarningDetails(payload);
      hideLoadingOverlay();
      const accepted = await showConfirmDialog(warning.message, {
        title: warning.title,
        confirmLabel: 'Import and overwrite',
      });
      if (!accepted) {
        await fetch(`/admin/import-export/import/uploads/${encodeURIComponent(uploadId)}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        }).catch(() => {});
        return;
      }
      confirmed.value = '1';
      showLoadingOverlay('Importing package', 'Please wait while Dashboard Analytic imports the selected package.');
      const importData = new FormData();
      importData.set('upload_id', uploadId);
      importData.set('confirmed_import', 'true');
      const importResponse = await fetch('/admin/import-export/import/jobs', {
        method: 'POST',
        body: importData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const importPayload = await importResponse.json().catch(() => ({}));
      if (!importResponse.ok || !importPayload.status_url) {
        throw new Error(importPayload.detail || 'The import could not be started.');
      }
      const pollImport = async () => {
        const statusResponse = await fetch(importPayload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const status = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(status.detail || 'The import status could not be read.');
        if (status.status === 'ready') {
          window.location.assign(`/admin?${new URLSearchParams({import_export_notice: status.notice || 'Package imported successfully.'})}`);
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'The package could not be imported.');
        if (loadingCopy) loadingCopy.textContent = 'Importing directly from the uploaded package on disk. Large workspaces can take several minutes; no second upload is required.';
        window.setTimeout(() => { pollImport().catch(handleImportError); }, 1200);
      };
      const handleImportError = (error) => {
        hideLoadingOverlay();
        showInfoDialog(error instanceof Error ? error.message : 'The package could not be imported.', {title: 'Import Package Error'});
      };
      pollImport().catch(handleImportError);
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The selected file could not be inspected.', {
        title: 'Import Package Error',
      });
    }
  });
});

function selectFullEnvironmentWorkspaces() {
  const overlay = document.querySelector('[data-full-environment-workspace-overlay]');
  if (!(overlay instanceof HTMLElement)) return Promise.resolve([]);
  const checkboxes = [...overlay.querySelectorAll('.full-environment-workspace-choice input[type="checkbox"]')];
  const accept = overlay.querySelector('[data-full-environment-accept]');
  const cancel = overlay.querySelector('[data-full-environment-cancel]');
  const selectAll = overlay.querySelector('[data-full-environment-select-all]');
  const selectNone = overlay.querySelector('[data-full-environment-select-none]');
  const error = overlay.querySelector('[data-full-environment-workspace-error]');
  overlay.hidden = false;
  document.body.classList.add('loading-active');
  if (error instanceof HTMLElement) error.hidden = true;
  return new Promise((resolve) => {
    const close = (selection) => {
      overlay.hidden = true;
      document.body.classList.remove('loading-active');
      accept?.removeEventListener('click', submit);
      cancel?.removeEventListener('click', dismiss);
      selectAll?.removeEventListener('click', checkAll);
      selectNone?.removeEventListener('click', clearAll);
      overlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      resolve(selection);
    };
    const submit = () => {
      const selected = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
      if (selected.length === 0) {
        if (error instanceof HTMLElement) error.hidden = false;
        return;
      }
      close(selected);
    };
    const dismiss = () => close(null);
    const checkAll = () => { checkboxes.forEach((checkbox) => { checkbox.checked = true; }); if (error instanceof HTMLElement) error.hidden = true; };
    const clearAll = () => { checkboxes.forEach((checkbox) => { checkbox.checked = false; }); };
    const backdrop = (event) => { if (event.target === overlay) dismiss(); };
    const keyboard = (event) => { if (event.key === 'Escape') dismiss(); };
    accept?.addEventListener('click', submit);
    cancel?.addEventListener('click', dismiss);
    selectAll?.addEventListener('click', checkAll);
    selectNone?.addEventListener('click', clearAll);
    overlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    if (accept instanceof HTMLElement) accept.focus();
  });
}

function selectTransferDestination() {
  const overlay = document.querySelector('[data-server-transfer-overlay]');
  if (!(overlay instanceof HTMLElement)) return Promise.resolve(null);
  const url = overlay.querySelector('[data-server-transfer-url]');
  const port = overlay.querySelector('[data-server-transfer-port]');
  const error = overlay.querySelector('[data-server-transfer-error]');
  const accept = overlay.querySelector('[data-server-transfer-connect]');
  const cancel = overlay.querySelector('[data-server-transfer-cancel]');
  overlay.hidden = false;
  document.body.classList.add('loading-active');
  if (error instanceof HTMLElement) error.hidden = true;
  return new Promise((resolve) => {
    const close = (value) => {
      overlay.hidden = true;
      document.body.classList.remove('loading-active');
      accept?.removeEventListener('click', submit);
      cancel?.removeEventListener('click', dismiss);
      overlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      resolve(value);
    };
    const submit = () => {
      const destinationUrl = url instanceof HTMLInputElement ? url.value.trim() : '';
      const destinationPort = port instanceof HTMLInputElement ? port.value.trim() : '';
      if (!destinationUrl) {
        if (error instanceof HTMLElement) {
          error.textContent = 'Enter the destination server URL or IP address.';
          error.hidden = false;
        }
        url?.focus();
        return;
      }
      if (destinationPort && (Number(destinationPort) < 1 || Number(destinationPort) > 65535)) {
        if (error instanceof HTMLElement) {
          error.textContent = 'The port must be between 1 and 65535.';
          error.hidden = false;
        }
        port?.focus();
        return;
      }
      close({destinationUrl, destinationPort});
    };
    const dismiss = () => close(null);
    const backdrop = (event) => { if (event.target === overlay) dismiss(); };
    const keyboard = (event) => { if (event.key === 'Escape') dismiss(); };
    accept?.addEventListener('click', submit);
    cancel?.addEventListener('click', dismiss);
    overlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    url?.focus();
  });
}

document.querySelectorAll('[data-export-package-form]').forEach((form) => {
  const exportTarget = form.querySelector('select[name="export_target"]');
  const transferButton = form.querySelector('[data-server-transfer]');
  let selectedFullWorkspaceIds = null;
  exportTarget?.addEventListener('change', async () => {
    if (!(exportTarget instanceof HTMLSelectElement) || exportTarget.value !== 'full-environment') {
      selectedFullWorkspaceIds = null;
      return;
    }
    const selection = await selectFullEnvironmentWorkspaces();
    if (selection === null) {
      exportTarget.value = 'config';
      selectedFullWorkspaceIds = null;
      return;
    }
    selectedFullWorkspaceIds = selection;
  });
  transferButton?.addEventListener('click', async () => {
    if (!(form instanceof HTMLFormElement)) return;
    const formData = new FormData(form);
    if (formData.get('export_target') === 'full-environment') {
      const workspaceIds = selectedFullWorkspaceIds || await selectFullEnvironmentWorkspaces();
      if (workspaceIds === null) return;
      selectedFullWorkspaceIds = workspaceIds;
      workspaceIds.forEach((workspaceId) => formData.append('workspace_ids', workspaceId));
    }
    const destination = await selectTransferDestination();
    if (!destination) return;
    formData.set('destination_url', destination.destinationUrl);
    if (destination.destinationPort) formData.set('destination_port', destination.destinationPort);
    showLoadingOverlay('Contacting destination server', 'Checking whether the destination server accepts the selected export.');
    const handleTransferError = (error) => {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The server transfer could not be completed.', {
        title: 'Server Transfer Error',
        tone: 'error',
      });
    };
    try {
      const response = await fetch('/admin/import-export/transfers/jobs', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.status_url) throw new Error(payload.detail || 'The transfer could not be started.');
      const pollTransfer = async () => {
        const statusResponse = await fetch(payload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const transfer = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(transfer.detail || 'The transfer status could not be read.');
        if (transfer.status === 'ready') {
          hideLoadingOverlay();
          showInfoDialog(transfer.notice || 'The destination server received and imported the package successfully.', {
            title: 'Server Transfer Complete',
            tone: 'info',
          });
          return;
        }
        if (transfer.status === 'failed') throw new Error(transfer.error || 'The destination server could not complete the transfer.');
        setLoadingProgress(transfer.status === 'transferring' ? transfer.progress : 0);
        const copies = {
          queued: 'Preparing the connection to the destination server.',
          connecting: 'Connecting to the destination server and creating the transfer request.',
          awaiting_acceptance: 'Waiting for a super-admin on the destination server to accept the transfer.',
          exporting: 'The destination accepted the transfer. Creating the selected export package.',
          transferring: `Sending the package to the destination server${transfer.progress ? ` — ${transfer.progress}%` : ''}.`,
          remote_importing: 'Package received. The destination server is importing it automatically.',
        };
        if (loadingCopy) loadingCopy.textContent = copies[transfer.status] || 'The server transfer is in progress.';
        window.setTimeout(() => { pollTransfer().catch(handleTransferError); }, 1500);
      };
      pollTransfer().catch(handleTransferError);
    } catch (error) {
      handleTransferError(error);
    }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!(form instanceof HTMLFormElement)) return;
    const formData = new FormData(form);
    if (formData.get('export_target') === 'full-environment') {
      const workspaceIds = selectedFullWorkspaceIds || await selectFullEnvironmentWorkspaces();
      if (workspaceIds === null) return;
      workspaceIds.forEach((workspaceId) => formData.append('workspace_ids', workspaceId));
    }
    showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.job_id || !payload.status_url) {
        throw new Error(payload.detail || 'The export package could not be started.');
      }
      const pollExport = async () => {
        const statusResponse = await fetch(payload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const status = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(status.detail || 'The export status could not be read.');
        if (status.status === 'ready' && status.download_url) {
          hideLoadingOverlay();
          const link = document.createElement('a');
          link.href = status.download_url;
          link.download = status.filename || 'dashboard-analytic-export.zip';
          document.body.appendChild(link);
          link.click();
          link.remove();
          showInfoDialog('The package is ready. Your browser download has started and can be resumed if necessary.', {
            title: 'Export Package Ready',
            tone: 'info',
          });
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'The export package could not be created.');
        setLoadingProgress(status.progress);
        if (loadingCopy) loadingCopy.textContent = status.progress > 0
          ? `Preparing the export package on the server — approximately ${status.progress}% of source data archived.`
          : 'Preparing the export package on the server. Large workspaces can take several minutes; you may keep this page open.';
        window.setTimeout(() => { pollExport().catch(handleExportError); }, 1200);
      };
      const handleExportError = (error) => {
        hideLoadingOverlay();
        showInfoDialog(error instanceof Error ? error.message : 'The export package could not be created.', {
          title: 'Export Package Error',
          tone: 'error',
        });
      };
      pollExport().catch(handleExportError);
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The export package could not be started.', {
        title: 'Export Package Error',
        tone: 'error',
      });
    }
  });
});

(() => {
  if (!document.querySelector('[data-server-transfer-listener]')) return;
  let reviewingOffer = false;
  let pollingOffers = false;
  const pollIncomingTransferOffers = async () => {
    if (reviewingOffer || pollingOffers) return;
    pollingOffers = true;
    try {
      const response = await fetch('/admin/import-export/transfers/offers', {
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
        cache: 'no-store',
      });
      if (!response.ok) return;
      const payload = await response.json().catch(() => ({}));
      const offer = Array.isArray(payload.offers) ? payload.offers[0] : null;
      if (!offer) return;
      reviewingOffer = true;
      const workspaceCopy = Array.isArray(offer.workspaces) && offer.workspaces.length
        ? `\nWorkspaces: ${offer.workspaces.join(', ')}`
        : '';
      const sourceAddress = offer.source_address ? ` (${offer.source_address})` : '';
      const accepted = await showConfirmDialog(
        `${offer.source}${sourceAddress} wants to transfer “${offer.content}” to this server.${workspaceCopy}\n\nAfter the complete package is received, it will be imported automatically and may overwrite matching configuration or workspaces.`,
        {title: 'Incoming server transfer', confirmLabel: 'Accept transfer', cancelLabel: 'Reject'},
      );
      const action = accepted ? 'accept' : 'reject';
      const decision = await fetch(`/admin/import-export/transfers/offers/${encodeURIComponent(offer.id)}/${action}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      if (!decision.ok) {
        const error = await decision.json().catch(() => ({}));
        showInfoDialog(error.detail || 'The transfer decision could not be saved.', {title: 'Incoming Transfer Error'});
      }
    } catch (_error) {
      // A transient polling failure should not interrupt the Admin page.
    } finally {
      reviewingOffer = false;
      pollingOffers = false;
    }
  };
  window.setInterval(pollIncomingTransferOffers, 3000);
  pollIncomingTransferOffers();
})();

document.querySelectorAll('form[data-loading-label]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.downloadForm === '1') {
      event.preventDefault();
      submitDownloadForm(form);
      return;
    }
    if (window.location.pathname === '/dashboard' && form.id === 'dashboard-dataset-form') {
      event.preventDefault();
      const params = buildDashboardParamsFromForm(form);
      if (!navigateToPersistedDatasetDashboard(
        params.get('dataset_id'),
        params.get('input_kind'),
        form.dataset.loadingLabel,
      )) {
        showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
        replaceLocation(buildDatasetDashboardUrl(params));
      }
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
    showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
  });
});

function showConfirmDialog(message, options = {}) {
  if (!confirmOverlay || !confirmTitle || !confirmCopy || !confirmAccept || !confirmCancel) {
    const accepted = window.confirm(message || 'Are you sure?');
    return Promise.resolve(options.optionLabel ? {accepted, optionChecked: false} : accepted);
  }

  confirmTitle.textContent = options.title || 'Confirm action';
  confirmCopy.textContent = message || options.copy || 'Are you sure you want to continue?';
  confirmAccept.textContent = options.confirmLabel || 'Confirm';
  confirmCancel.textContent = options.cancelLabel || 'Cancel';
  confirmCancel.hidden = options.hideCancel === true;
  const hasOption = Boolean(options.optionLabel && confirmOption && confirmOptionInput && confirmOptionLabel);
  if (hasOption) {
    confirmOptionLabel.textContent = options.optionLabel;
    confirmOptionInput.checked = false;
    confirmOption.hidden = false;
  }
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
      confirmCancel.hidden = false;
      confirmCancel.textContent = 'Cancel';
      const optionChecked = hasOption && Boolean(confirmOptionInput?.checked);
      if (confirmOption) confirmOption.hidden = true;
      if (confirmOptionInput) confirmOptionInput.checked = false;
      resolve(hasOption ? {accepted, optionChecked} : accepted);
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

function showCatalogueInsertChoice(slide) {
  if (!catalogueInsertOverlay || !catalogueInsertTitle || !catalogueInsertCopy || !catalogueInsertChart || !catalogueInsertSlide || !catalogueInsertCancel) {
    const response = window.prompt(`Slide ${slide}: type chart to add a chart, or slide to add a new slide.`, 'chart');
    return Promise.resolve(response?.trim().toLocaleLowerCase() === 'slide' ? 'slide' : response?.trim().toLocaleLowerCase() === 'chart' ? 'chart' : null);
  }
  catalogueInsertTitle.textContent = `Add after slide ${slide}`;
  catalogueInsertCopy.textContent = 'Add another chart to this slide, or insert a new blank slide after it. A new slide renumbers the following slides.';
  catalogueInsertOverlay.hidden = false;
  document.body.classList.add('loading-active');
  return new Promise((resolve) => {
    const close = (choice) => {
      catalogueInsertOverlay.hidden = true;
      document.body.classList.remove('loading-active');
      catalogueInsertChart.removeEventListener('click', addChart);
      catalogueInsertSlide.removeEventListener('click', addSlide);
      catalogueInsertCancel.removeEventListener('click', cancel);
      catalogueInsertOverlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      resolve(choice);
    };
    const addChart = () => close('chart');
    const addSlide = () => close('slide');
    const cancel = () => close(null);
    const backdrop = (event) => { if (event.target === catalogueInsertOverlay) cancel(); };
    const keyboard = (event) => { if (event.key === 'Escape') cancel(); };
    catalogueInsertChart.addEventListener('click', addChart);
    catalogueInsertSlide.addEventListener('click', addSlide);
    catalogueInsertCancel.addEventListener('click', cancel);
    catalogueInsertOverlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    catalogueInsertChart.focus();
  });
}

function showInfoDialog(message, options = {}) {
  if (!infoOverlay || !infoTitle || !infoCopy || !infoClose) {
    window.alert(message || 'Update complete');
    options.onClose?.();
    return;
  }
  const tone = ['info', 'warning', 'error'].includes(options.tone) ? options.tone : 'info';
  const toneLabels = {info: 'Information', warning: 'Warning', error: 'Error'};
  const toneIcons = {info: 'i', warning: '!', error: '×'};
  infoOverlay.dataset.tone = tone;
  if (infoEyebrow) infoEyebrow.textContent = toneLabels[tone];
  if (infoIcon) infoIcon.textContent = toneIcons[tone];
  infoTitle.textContent = options.title || toneLabels[tone];
  infoCopy.textContent = message || '';
  infoOverlay.hidden = false;
  document.body.classList.add('loading-active');
  const close = () => {
    infoOverlay.hidden = true;
    delete infoOverlay.dataset.tone;
    document.body.classList.remove('loading-active');
    infoClose.removeEventListener('click', close);
    infoOverlay.removeEventListener('click', handleBackdrop);
    window.removeEventListener('keydown', handleKeydown);
    options.onClose?.();
  };
  const handleBackdrop = (event) => { if (event.target === infoOverlay) close(); };
  const handleKeydown = (event) => { if (event.key === 'Escape') close(); };
  infoClose.addEventListener('click', close);
  infoOverlay.addEventListener('click', handleBackdrop);
  window.addEventListener('keydown', handleKeydown);
  infoClose.focus();
}

(() => {
  const openButton = document.querySelector('[data-change-password-open]');
  const overlay = document.getElementById('change-password-overlay');
  const form = document.querySelector('[data-change-password-form]');
  const cancel = document.querySelector('[data-change-password-cancel]');
  const error = document.querySelector('[data-change-password-error]');
  if (!openButton || !overlay || !form || !cancel) return;
  const close = () => { overlay.hidden = true; form.reset(); if (error) error.hidden = true; };
  const open = () => { overlay.hidden = false; form.querySelector('input')?.focus(); };
  openButton.addEventListener('click', open);
  openButton.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
  cancel.addEventListener('click', close);
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (error) error.hidden = true;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const response = await fetch('/account/change-password', {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'The password could not be changed.');
      close();
      showInfoDialog('Your password has been changed successfully.', {title: 'Password changed', tone: 'info'});
    } catch (requestError) {
      if (error) { error.textContent = requestError.message; error.hidden = false; }
    } finally {
      if (submit) submit.disabled = false;
    }
  });
})();

function clearCatalogueImportQuery() {
  const url = new URL(window.location.href);
  url.searchParams.delete('catalogue_notice');
  url.searchParams.delete('catalogue_error');
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

const catalogueImportError = document.querySelector('[data-catalogue-import-error]');
if (catalogueImportError?.textContent.trim()) {
  requestAnimationFrame(() => {
    showInfoDialog(catalogueImportError.textContent.trim(), {
      title: 'Slides Templates Import Failed',
      onClose: clearCatalogueImportQuery,
    });
  });
}

const catalogueImportNotice = document.querySelector('[data-catalogue-import-notice]');
if (catalogueImportNotice?.textContent.trim()) {
  requestAnimationFrame(() => {
    showInfoDialog(catalogueImportNotice.textContent.trim(), {
      title: 'Slides Templates Imported',
      onClose: clearCatalogueImportQuery,
    });
  });
}

function bindConfirmForm(form) {
  if (form.dataset.confirmBound === '1') return;
  form.dataset.confirmBound = '1';
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const accepted = await showConfirmDialog(form.dataset.confirm, {
      title: form.dataset.confirmTitle || 'Confirm action',
      confirmLabel: form.dataset.confirmLabel || 'Confirm',
    });
    if (accepted) {
      const parentDialog = form.closest('dialog');
      if (parentDialog?.open) {
        parentDialog.close();
      }
      if (form.dataset.confirmLoadingLabel) {
        showLoadingOverlay(form.dataset.confirmLoadingLabel, form.dataset.confirmLoadingCopy);
      }
      if (form.action.includes('/admin/report-templates/')) {
        preserveAdminScrollPosition();
      }
      form.submit();
    }
  });
}

document.querySelectorAll('form[data-confirm]').forEach(bindConfirmForm);

function sizeAdminDatasetNameColumn(panel = document) {
  const table = panel.querySelector?.('.admin-datasets-table');
  const nameColumn = table?.querySelector('[data-admin-dataset-name-column]');
  const inputs = table?.querySelectorAll('[data-admin-dataset-name-input]');
  if (!table || !nameColumn || !inputs?.length) return;

  const probe = document.createElement('span');
  const sample = inputs[0];
  const styles = window.getComputedStyle(sample);
  probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${styles.font};letter-spacing:${styles.letterSpacing};`;
  document.body.appendChild(probe);
  const longest = Math.max(...Array.from(inputs, (input) => {
    probe.textContent = input.value;
    return probe.getBoundingClientRect().width;
  }));
  probe.remove();
  nameColumn.style.width = `${Math.ceil(longest + 82)}px`;
}

function bindAdminDatasetRenameForm(form) {
  if (form.dataset.renameBound === '1') return;
  form.dataset.renameBound = '1';
  const input = form.querySelector('[data-admin-dataset-name-input]');
  const save = form.querySelector('[data-admin-dataset-rename-save]');
  if (!(input instanceof HTMLInputElement) || !(save instanceof HTMLButtonElement)) return;
  const savedName = input.value;

  input.addEventListener('focus', () => { save.hidden = false; });
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      if (document.activeElement === input) return;
      input.value = savedName;
      save.hidden = true;
    }, 120);
  });
  // Keep focus on the field while the button is pressed so blur does not hide
  // the confirmation control before its form submission is dispatched.
  save.addEventListener('mousedown', (event) => event.preventDefault());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showLoadingOverlay(
      'Renaming dataset',
      'Please wait while the dataset file, path and materialised references are updated.',
    );
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin', redirect: 'follow',
      });
      const content = await response.text();
      if (!response.ok) {
        let message = `The dataset could not be renamed (status ${response.status}).`;
        try { message = JSON.parse(content).detail || message; } catch (_error) { /* Use fallback message. */ }
        throw new Error(message);
      }
      const refreshedDocument = new DOMParser().parseFromString(content, 'text/html');
      const refreshedPanel = refreshedDocument.querySelector('[data-panel-state-key="admin:datasets"]');
      const currentPanel = form.closest('[data-panel-state-key="admin:datasets"]');
      if (!refreshedPanel || !currentPanel) throw new Error('The refreshed Datasets Management panel is unavailable.');
      refreshedPanel.open = currentPanel.open;
      currentPanel.replaceWith(refreshedPanel);
      refreshedPanel.querySelectorAll('form[data-confirm]').forEach(bindConfirmForm);
      refreshedPanel.querySelectorAll('[data-admin-dataset-rename-form]').forEach(bindAdminDatasetRenameForm);
      window.requestAnimationFrame(() => sizeAdminDatasetNameColumn(refreshedPanel));
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'The dataset could not be renamed.', {
        title: 'Dataset Rename Failed', tone: 'error',
      });
    } finally {
      hideLoadingOverlay();
    }
  });
}

document.querySelectorAll('[data-admin-dataset-rename-form]').forEach(bindAdminDatasetRenameForm);

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

const appLogsPanel = document.querySelector('[data-app-logs-panel]');
if (appLogsPanel) {
  const appLogFiltersStorageKey = 'dashboard-analytic:/app-logs:filters';
  const userFilter = appLogsPanel.querySelector('[data-app-log-user-filter]');
  const dateFilter = appLogsPanel.querySelector('[data-app-log-date-filter]');
  const typeFilter = appLogsPanel.querySelector('[data-app-log-type-filter]');
  const actionFilter = appLogsPanel.querySelector('[data-app-log-action-filter]');
  const clearFilters = appLogsPanel.querySelector('[data-app-log-clear-filters]');
  const noResults = appLogsPanel.querySelector('[data-app-log-no-results]');
  const rows = Array.from(appLogsPanel.querySelectorAll('[data-app-log-row]'));
  const restoreSelectValue = (control, value) => {
    if (!control || !value) return;
    if (Array.from(control.options).some((option) => option.value === value)) control.value = value;
  };
  try {
    const savedFilters = JSON.parse(window.localStorage.getItem(appLogFiltersStorageKey) || '{}');
    restoreSelectValue(userFilter, savedFilters.user);
    if (dateFilter && /^\d{4}-\d{2}-\d{2}$/.test(savedFilters.date || '')) dateFilter.value = savedFilters.date;
    restoreSelectValue(typeFilter, savedFilters.type);
    restoreSelectValue(actionFilter, savedFilters.action);
  } catch (_error) {
    // The log view remains fully usable when browser storage is unavailable.
  }
  const persistAppLogFilters = () => {
    try {
      window.localStorage.setItem(appLogFiltersStorageKey, JSON.stringify({
        user: userFilter?.value || 'all', date: dateFilter?.value || '',
        type: typeFilter?.value || 'all', action: actionFilter?.value || 'all',
      }));
    } catch (_error) {
      // Persistence is a convenience and must not block filtering.
    }
  };
  const syncAppLogRows = () => {
    let visibleCount = 0;
    rows.forEach((row) => {
      const matches = (
        (!userFilter || userFilter.value === 'all' || row.dataset.appLogUser === userFilter.value)
        && (!dateFilter || !dateFilter.value || row.dataset.appLogDate === dateFilter.value)
        && (!typeFilter || typeFilter.value === 'all' || row.dataset.appLogType === typeFilter.value)
        && (!actionFilter || actionFilter.value === 'all' || row.dataset.appLogAction === actionFilter.value)
      );
      row.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    if (noResults) noResults.hidden = visibleCount > 0 || rows.length === 0;
  };
  [userFilter, dateFilter, typeFilter, actionFilter].filter(Boolean).forEach((filter) => filter.addEventListener('change', () => {
    persistAppLogFilters();
    syncAppLogRows();
  }));
  clearFilters?.addEventListener('click', () => {
    if (userFilter) userFilter.value = 'all';
    if (dateFilter) dateFilter.value = '';
    if (typeFilter) typeFilter.value = 'all';
    if (actionFilter) actionFilter.value = 'all';
    try { window.localStorage.removeItem(appLogFiltersStorageKey); } catch (_error) { /* Ignore unavailable browser storage. */ }
    syncAppLogRows();
  });
  syncAppLogRows();
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
  let refreshWorkspaceAfterCompletion = false;
  const selectedDatasetField = document.querySelector('input[name="dataset_id"], select[name="dataset_id"]');
  const waitingPanel = document.querySelector('.queue-waiting-copy');
  const queueTypeFilter = document.querySelector('[data-queue-type-filter]');
  const applyQueueTypeFilter = () => {
    const selectedKind = queueTypeFilter?.value || '';
    document.querySelectorAll('[data-dataset-row]').forEach((row) => {
      row.hidden = Boolean(selectedKind && row.dataset.datasetKind !== selectedKind);
    });
  };
  queueTypeFilter?.addEventListener('change', applyQueueTypeFilter);
  applyQueueTypeFilter();
  const formatQueueTimestamp = (value) => String(value || '').replace('T', ' ').replace(' ', '\n');

  const updateQueueRow = (dataset) => {
    const row = document.querySelector(`[data-dataset-row][data-dataset-id="${dataset.id}"]`);
    if (!row) return;
    const kind = row.querySelector('[data-queue-kind]');
    const rows = row.querySelector('[data-queue-rows]');
    const size = row.querySelector('[data-queue-size]');
    const statusPill = row.querySelector('[data-queue-status-pill]');
    const progressBar = row.querySelector('[data-queue-progress-bar]');
    const progressLabel = row.querySelector('[data-queue-progress-label]');
    const uploaded = row.querySelector('[data-queue-uploaded]');
    const updated = row.querySelector('[data-queue-updated]');
    const actions = row.querySelector('.queue-actions');
    let errorNode = row.querySelector('[data-queue-error]');
    const previousStatus = row.dataset.queueStatus
      || (statusPill?.classList.contains('queue-status-ready') ? 'ready' : '');

    if (kind) kind.textContent = dataset.input_kind_label || 'Other';
    if (rows) rows.textContent = String(dataset.row_count || 0);
    if (size) size.textContent = dataset.size_mb_label || '0.00 MB';
    if (statusPill) {
      statusPill.textContent = dataset.status_label || dataset.status || 'Queued';
      statusPill.className = `queue-status-pill queue-status-${dataset.status}`;
    }
    row.dataset.queueStatus = dataset.status || '';
    if (previousStatus && previousStatus !== 'ready' && dataset.status === 'ready') {
      refreshWorkspaceAfterCompletion = true;
    }
    if (progressBar) {
      progressBar.style.width = `${dataset.progress || 0}%`;
      progressBar.className = `progress-bar status-${dataset.status}`;
    }
    if (progressLabel) progressLabel.textContent = `${dataset.progress || 0}%`;
    if (uploaded) uploaded.textContent = formatQueueTimestamp(dataset.uploaded_at_local || dataset.uploaded_at);
    if (updated) updated.textContent = formatQueueTimestamp(dataset.updated_at_local || dataset.updated_at || dataset.uploaded_at_local || dataset.uploaded_at);
    // A profile can be in the small persistence window between status updates.
    // Keep the known row kind until the API supplies a replacement so ready CDR
    // actions do not disappear while another upload is being processed.
    const datasetKind = dataset.dataset_kind || row.dataset.datasetKind || 'generic';
    row.dataset.datasetKind = datasetKind;
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
      if (datasetKind && datasetKind !== 'generic') {
        openParams.set('input_kind', String(datasetKind));
      }
      const openHref = `/dashboard?${openParams.toString()}`;
      const isCdr = ['data', 'voice', 'speech'].includes(datasetKind);
      const hadMapVendors = Boolean(actions.querySelector('[data-vendor-map-open]'));
      const hadClearVendors = Boolean(actions.querySelector('[data-vendor-clear-open]'));
      // Preserve already available Vendor actions during live polling. New
      // actions still come directly from the persisted API capabilities.
      const canMapVendors = Boolean(dataset.can_map_vendors) || hadMapVendors;
      const canClearVendors = Boolean(dataset.can_clear_vendors) || hadClearVendors;
      const fileName = String(dataset.file_name || 'dataset')
        .replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      if (dataset.status === 'ready') {
        actions.innerHTML = `
          <a class="ghost-link action-link-preview" href="/workspace/preview/${dataset.id}" target="_blank" rel="noopener" data-preview-open-link data-loading-label="Generating dataset preview">Preview</a>
          <form method="post" action="/dashboard/delete/${dataset.id}" data-confirm="Delete dataset '${fileName}'?" data-confirm-title="Delete dataset" data-confirm-label="Delete dataset">
            <button type="submit" class="danger-button">Delete</button>
          </form>
          ${isCdr ? `<a class="ghost-link action-link-primary" href="${openHref}" data-dashboard-open-link data-dataset-id="${dataset.id}"${datasetKind ? ` data-input-kind="${String(datasetKind)}"` : ''}>Show Dashboard</a>` : ''}
          ${canClearVendors ? `<button type="button" class="action-link-clear-vendors" data-vendor-clear-open data-dataset-id="${dataset.id}">Clear Vendors</button>` : ''}
          ${canMapVendors ? `<button type="button" class="ghost-link action-link-map-vendors" data-vendor-map-open data-dataset-id="${dataset.id}" data-dataset-name="${fileName}">Map Vendors</button>` : ''}
        `;
      } else if (dataset.status === 'processing') {
        actions.innerHTML = `
          <span class="ghost-link action-link-disabled" aria-disabled="true">Preview</span>
          <form method="post" action="/dashboard/stop/${dataset.id}" data-confirm="Stop processing for '${dataset.file_name}'?" data-confirm-title="Stop processing" data-confirm-label="Stop processing">
            <button type="submit" class="danger-button">Stop</button>
          </form>
        `;
      } else if (dataset.status === 'queued') {
        actions.innerHTML = `
          <span class="ghost-link action-link-disabled" aria-disabled="true">Preview</span>
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
      applyQueueTypeFilter();
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
      const response = await fetch(url, {cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok) return;
      const payload = await response.json();
      const datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
      datasets.forEach(updateQueueRow);
      if (refreshWorkspaceAfterCompletion) {
        // A complete reload obtains the final server-rendered action set,
        // including Map/Clear Vendors, after background processing finishes.
        window.location.reload();
        return;
      }
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
