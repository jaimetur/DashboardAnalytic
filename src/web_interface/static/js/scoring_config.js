(() => {
  const root = document.querySelector('[data-scoring-config]');
  if (!root) return;

  const endpoint = '/api/workspace-config/scoring-configuration';
  const environmentSelect = root.querySelector('[data-scoring-environment]');
  const kpiForm = root.querySelector('[data-scoring-kpi-form]');
  const kpiRows = root.querySelector('[data-scoring-kpi-rows]');
  const kpiStatus = root.querySelector('[data-scoring-kpi-status]');
  const kpiSave = root.querySelector('[data-scoring-kpi-save]');
  const priorityForm = root.querySelector('[data-scoring-priority-form]');
  const priorityRows = root.querySelector('[data-scoring-priority-rows]');
  const priorityStatus = root.querySelector('[data-scoring-priority-status]');
  const prioritySave = root.querySelector('[data-scoring-priority-save]');
  if (!environmentSelect || !kpiForm || !kpiRows || !priorityForm || !priorityRows) return;

  const anchors = [
    ['low_score', 'Low score'],
    ['medium_score', 'Medium score'],
    ['high_score', 'High score'],
    ['ultra_score', 'Ultra score'],
  ];
  let configuration = null;
  let kpiDirty = false;
  let lastEnvironment = environmentSelect.value;
  let saveQueue = Promise.resolve();

  const setStatus = (element, message, tone = '') => {
    if (!element) return;
    element.textContent = message;
    element.classList.toggle('is-error', tone === 'error');
    element.classList.toggle('is-success', tone === 'success');
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {})},
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
    return payload;
  };

  const loadConfiguration = () => requestJson(endpoint);
  const importButton = root.querySelector('[data-scoring-config-import]');
  const importFile = root.querySelector('[data-scoring-config-file]');
  importButton?.addEventListener('click', () => importFile?.click());
  importFile?.addEventListener('change', async () => {
    const file = importFile.files?.[0];
    if (!file) return;
    if (configuration && !window.confirm('Replace this workspace\'s scoring configuration with the selected JSON? Saved jobs retain their original rules.')) {
      importFile.value = '';
      return;
    }
    const body = new FormData();
    body.append('package', file);
    importButton.disabled = true;
    try {
      const response = await fetch(`${endpoint}/import`, {method: 'POST', credentials: 'same-origin', body});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Unable to import scoring configuration.');
      configuration = payload;
      kpiDirty = false;
      render();
      if (kpiSave) kpiSave.disabled = false;
      if (prioritySave) prioritySave.disabled = false;
      setStatus(kpiStatus, 'Scoring configuration imported into this workspace.', 'success');
      setStatus(priorityStatus, 'GAP KPI priority imported.', 'success');
    } catch (error) {
      setStatus(kpiStatus, error.message || 'Unable to import scoring configuration.', 'error');
    } finally {
      importButton.disabled = false;
      importFile.value = '';
    }
  });

  const saveConfiguration = (nextConfiguration) => {
    const work = saveQueue.then(async () => {
      const latest = await loadConfiguration();
      const merged = nextConfiguration(latest);
      return requestJson(endpoint, {method: 'PUT', body: JSON.stringify(merged)});
    });
    saveQueue = work.catch(() => {});
    return work;
  };

  const appendCell = (row, className = '') => {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    row.append(cell);
    return cell;
  };

  const appendNumericInput = (cell, value, label, attributes = {}) => {
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.value = Number.isFinite(Number(value)) ? String(value) : '';
    input.setAttribute('aria-label', label);
    Object.entries(attributes).forEach(([key, attributeValue]) => input.setAttribute(key, String(attributeValue)));
    cell.append(input);
    return input;
  };

  const rowMetrics = () => Array.from(kpiRows.querySelectorAll('tr[data-kpi-code]'));

  const updateDerivedWeights = () => {
    const rows = rowMetrics();
    const selectedEnvironment = environmentSelect.value;
    const otherEnvironment = selectedEnvironment === 'DriveCity' ? 'DriveConnectionroad' : 'DriveCity';
    const selectedTotal = rows.reduce((sum, row) => {
      const value = Number(row.querySelector('[data-max-points]')?.value);
      return sum + (Number.isFinite(value) ? value : 0);
    }, 0);
    const otherTotal = (configuration?.metrics || []).reduce((sum, metric) => {
      const value = Number(metric.contexts?.[otherEnvironment]?.max_points);
      return sum + (Number.isFinite(value) ? value : 0);
    }, 0);
    const total = selectedTotal + otherTotal;
    rows.forEach((row) => {
      const points = Number(row.querySelector('[data-max-points]')?.value);
      const output = row.querySelector('[data-weight-percent]');
      output.textContent = Number.isFinite(points) && total > 0 ? `${(points * 100 / total).toFixed(2)}%` : '—';
    });
  };

  const syncUltraInput = (row) => {
    const mode = row.querySelector('[data-ultra-mode]')?.value;
    const input = row.querySelector('[data-ultra-value]');
    const note = row.querySelector('[data-ultra-note]');
    if (input) {
      input.hidden = mode !== 'fixed';
      input.disabled = mode !== 'fixed';
      input.required = mode === 'fixed';
    }
    if (note) {
      note.hidden = mode === 'fixed' || mode === 'none';
      note.textContent = mode === 'best_min' || mode === 'best_max' ? 'Uses the best observed KPI result.' : '';
    }
  };

  const renderKpiRows = () => {
    const environment = environmentSelect.value;
    kpiRows.replaceChildren();
    const metrics = Array.isArray(configuration?.metrics) ? configuration.metrics : [];
    metrics.forEach((metric) => {
      const context = metric.contexts?.[environment];
      if (!context) return;
      const row = document.createElement('tr');
      row.dataset.kpiCode = metric.code;

      const kpiCell = appendCell(row, 'scoring-config-kpi-label');
      kpiCell.append(document.createTextNode(metric.kpi || metric.code));
      const code = document.createElement('span');
      code.className = 'scoring-config-kpi-code';
      code.textContent = `${metric.code} · ${metric.category || 'Other'} · ${metric.direction === 'lower_is_better' ? 'Lower is better' : 'Higher is better'}`;
      kpiCell.append(code);

      const typeCell = appendCell(row);
      const typeInput = document.createElement('input');
      typeInput.className = 'scoring-config-type-input';
      typeInput.type = 'text';
      typeInput.required = true;
      typeInput.maxLength = 80;
      typeInput.value = metric.kpi_type || '';
      typeInput.dataset.kpiType = '';
      typeInput.setAttribute('aria-label', `Type of KPI for ${metric.kpi || metric.code}`);
      typeCell.append(typeInput);

      const pointsCell = appendCell(row);
      appendNumericInput(pointsCell, context.max_points, `Maximum points for ${metric.kpi || metric.code}`, {'data-max-points': '', min: '0', required: ''});
      const weightCell = appendCell(row);
      weightCell.className = 'scoring-config-weight';
      weightCell.dataset.weightPercent = '';

      for (const key of ['low', 'medium', 'high']) {
        const cell = appendCell(row);
        appendNumericInput(cell, context.thresholds?.[key], `${key} KPI threshold for ${metric.kpi || metric.code}`, {'data-threshold': key, required: ''});
      }

      const ultraCell = appendCell(row);
      ultraCell.className = 'scoring-config-ultra';
      const ultraSelect = document.createElement('select');
      ultraSelect.dataset.ultraMode = '';
      ultraSelect.setAttribute('aria-label', `Ultra threshold type for ${metric.kpi || metric.code}`);
      const ultra = context.thresholds?.ultra;
      const ultraMode = ultra === null || ultra === undefined ? 'none' : typeof ultra === 'object' ? String(ultra.rule || 'none') : 'fixed';
      const options = [
        ['none', 'None'], ['fixed', 'Fixed value'], ['best_min', 'Best minimum'], ['best_max', 'Best maximum'],
      ];
      options.forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        if ((value === 'best_min' && metric.direction !== 'lower_is_better')
            || (value === 'best_max' && metric.direction !== 'higher_is_better')) option.disabled = true;
        if (value === ultraMode) option.selected = true;
        ultraSelect.append(option);
      });
      ultraCell.append(ultraSelect);
      appendNumericInput(
        ultraCell, typeof ultra === 'number' ? ultra : '', `Fixed Ultra threshold for ${metric.kpi || metric.code}`,
        {'data-ultra-value': '', required: ''},
      );
      const ultraNote = document.createElement('small');
      ultraNote.dataset.ultraNote = '';
      ultraCell.append(ultraNote);
      ultraSelect.addEventListener('change', () => syncUltraInput(row));
      syncUltraInput(row);

      const mapping = context.score_mapping || {};
      anchors.forEach(([key, label]) => {
        const cell = appendCell(row);
        appendNumericInput(cell, Number(mapping[key]) * 100, `${label} interpolation anchor for ${metric.kpi || metric.code}`, {
          'data-score-anchor': key, min: '0', max: '100', required: '',
        });
      });

      const sourceCell = appendCell(row, 'scoring-config-source');
      const sourceDetails = document.createElement('details');
      sourceDetails.className = 'scoring-config-source';
      const summary = document.createElement('summary');
      summary.textContent = 'View formula and filters';
      const sourceText = document.createElement('pre');
      const calculation = metric.calculation || {};
      sourceText.textContent = [
        `Formula: ${calculation.formula || 'Not specified'}`,
        `Filters: ${JSON.stringify(calculation.filters || {}, null, 2)}`,
        `Source: ${JSON.stringify(metric.source || {}, null, 2)}`,
      ].join('\n\n');
      sourceDetails.append(summary, sourceText);
      sourceCell.append(sourceDetails);

      kpiRows.append(row);
    });
    updateDerivedWeights();
    if (kpiSave) kpiSave.disabled = false;
  };

  const priorityLabel = (code) => {
    const metric = (configuration?.metrics || []).find((item) => item.code === code);
    return metric ? `${metric.kpi || metric.code} (${metric.code})` : code;
  };

  const refreshPriorityButtons = () => {
    const rows = Array.from(priorityRows.querySelectorAll('tr[data-kpi-code]'));
    rows.forEach((row, index) => {
      row.querySelector('[data-priority-move="up"]').disabled = index === 0;
      row.querySelector('[data-priority-move="down"]').disabled = index === rows.length - 1;
      row.querySelector('[data-priority-rank]').textContent = String(index + 1);
    });
    if (prioritySave) prioritySave.disabled = rows.length === 0;
  };

  const renderPriorityRows = () => {
    priorityRows.replaceChildren();
    const knownCodes = (configuration?.metrics || []).map((metric) => metric.code);
    const savedCodes = Array.isArray(configuration?.gap_priority) ? configuration.gap_priority : [];
    const orderedCodes = [...new Set([...savedCodes, ...knownCodes])].filter((code) => knownCodes.includes(code));
    orderedCodes.forEach((code, index) => {
      const row = document.createElement('tr');
      row.dataset.kpiCode = code;
      const rankCell = appendCell(row);
      const rank = document.createElement('span');
      rank.dataset.priorityRank = '';
      rank.textContent = String(index + 1);
      rankCell.append(rank);
      appendCell(row).textContent = priorityLabel(code);
      const actions = document.createElement('div');
      actions.className = 'scoring-config-priority-actions';
      for (const [direction, label] of [['up', 'Move up'], ['down', 'Move down']]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.priorityMove = direction;
        button.setAttribute('aria-label', `${label}: ${priorityLabel(code)}`);
        button.title = label;
        button.textContent = direction === 'up' ? '↑' : '↓';
        actions.append(button);
      }
      appendCell(row).append(actions);
      priorityRows.append(row);
    });
    refreshPriorityButtons();
  };

  const render = () => {
    renderKpiRows();
    renderPriorityRows();
  };

  const readNumeric = (row, selector, label) => {
    const input = row.querySelector(selector);
    if (!input || !input.value.trim()) throw new Error(`${label} is required.`);
    const value = Number(input.value);
    if (!Number.isFinite(value)) throw new Error(`${label} must be a finite number.`);
    if (!input.checkValidity()) {
      input.reportValidity();
      throw new Error(`${label} has an invalid value.`);
    }
    return value;
  };

  const saveKpis = async () => {
    setStatus(kpiStatus, 'Saving KPI configuration…');
    if (kpiSave) kpiSave.disabled = true;
    try {
      const environment = environmentSelect.value;
      const saved = await saveConfiguration((latest) => {
        for (const row of rowMetrics()) {
          const metric = (latest.metrics || []).find((item) => item.code === row.dataset.kpiCode);
          const context = metric?.contexts?.[environment];
          if (!metric || !context) throw new Error(`KPI ${row.dataset.kpiCode} is no longer available.`);
          const type = row.querySelector('[data-kpi-type]').value.trim();
          if (!type) throw new Error(`Type of KPI is required for ${metric.kpi}.`);
          metric.kpi_type = type;
          context.max_points = readNumeric(row, '[data-max-points]', `Maximum points for ${metric.kpi}`);
          context.thresholds = context.thresholds || {};
          for (const key of ['low', 'medium', 'high']) {
            context.thresholds[key] = readNumeric(row, `[data-threshold="${key}"]`, `${key} threshold for ${metric.kpi}`);
          }
          const ultraMode = row.querySelector('[data-ultra-mode]').value;
          if (ultraMode === 'none') {
            context.thresholds.ultra = null;
          } else if (ultraMode === 'fixed') {
            context.thresholds.ultra = readNumeric(row, '[data-ultra-value]', `Ultra threshold for ${metric.kpi}`);
          } else {
            const previous = context.thresholds.ultra;
            context.thresholds.ultra = {
              rule: ultraMode,
              ...(previous && typeof previous === 'object' && previous.source_formula
                ? {source_formula: previous.source_formula} : {}),
            };
          }
          context.score_mapping = context.score_mapping || {};
          anchors.forEach(([key, label]) => {
            context.score_mapping[key] = readNumeric(row, `[data-score-anchor="${key}"]`, `${label} for ${metric.kpi}`) / 100;
          });
        }
        return latest;
      });
      configuration = saved;
      kpiDirty = false;
      renderKpiRows();
      setStatus(kpiStatus, 'KPI configuration saved.', 'success');
    } catch (error) {
      setStatus(kpiStatus, error.message || 'Unable to save KPI configuration.', 'error');
    } finally {
      if (kpiSave) kpiSave.disabled = false;
    }
  };

  const savePriority = async () => {
    setStatus(priorityStatus, 'Saving GAP KPI priority…');
    if (prioritySave) prioritySave.disabled = true;
    try {
      const codes = Array.from(priorityRows.querySelectorAll('tr[data-kpi-code]'), (row) => row.dataset.kpiCode);
      const saved = await saveConfiguration((latest) => {
        latest.gap_priority = [...codes];
        return latest;
      });
      configuration = saved;
      renderPriorityRows();
      setStatus(priorityStatus, 'GAP KPI priority saved.', 'success');
    } catch (error) {
      setStatus(priorityStatus, error.message || 'Unable to save GAP KPI priority.', 'error');
    } finally {
      if (prioritySave) prioritySave.disabled = false;
    }
  };

  kpiForm.addEventListener('input', (event) => {
    kpiDirty = true;
    setStatus(kpiStatus, 'Unsaved KPI changes.');
    if (event.target.matches('[data-max-points]')) updateDerivedWeights();
  });
  kpiForm.addEventListener('change', () => {
    kpiDirty = true;
    setStatus(kpiStatus, 'Unsaved KPI changes.');
  });
  kpiForm.addEventListener('submit', (event) => {
    event.preventDefault();
    saveKpis();
  });
  environmentSelect.addEventListener('change', () => {
    if (kpiDirty && !window.confirm('Discard unsaved KPI changes before switching environment?')) {
      environmentSelect.value = lastEnvironment;
      return;
    }
    kpiDirty = false;
    lastEnvironment = environmentSelect.value;
    renderKpiRows();
    setStatus(kpiStatus, '');
  });

  priorityForm.addEventListener('click', (event) => {
    const button = event.target.closest('[data-priority-move]');
    if (!button || !priorityRows.contains(button)) return;
    const row = button.closest('tr[data-kpi-code]');
    const neighbor = button.dataset.priorityMove === 'up' ? row.previousElementSibling : row.nextElementSibling;
    if (!row || !neighbor) return;
    if (button.dataset.priorityMove === 'up') priorityRows.insertBefore(row, neighbor);
    else priorityRows.insertBefore(neighbor, row);
    refreshPriorityButtons();
    setStatus(priorityStatus, 'Unsaved GAP KPI priority changes.');
  });
  priorityForm.addEventListener('submit', (event) => {
    event.preventDefault();
    savePriority();
  });

  loadConfiguration().then((loaded) => {
    configuration = loaded;
    render();
  }).catch((error) => {
    setStatus(kpiStatus, error.message || 'Unable to load scoring configuration.', 'error');
    setStatus(priorityStatus, error.message || 'Unable to load GAP KPI priority.', 'error');
    if (kpiSave) kpiSave.disabled = true;
    if (prioritySave) prioritySave.disabled = true;
  });
})();
