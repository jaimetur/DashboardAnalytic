(() => {
  const root = document.querySelector('[data-scoring-workspace]');
  if (!root) return;

  const jobsUrl = root.dataset.jobsUrl || '/api/scoring/jobs';
  const exportBase = root.dataset.exportBase || '/scoring/jobs';
  const requestedJobId = new URLSearchParams(window.location.search).get('job_id');
  const nrFilter = root.querySelector('[data-nr-filter]');
  const datasetOptions = [...root.querySelectorAll('[data-dataset-option]')];
  const datasetInputs = [...root.querySelectorAll('[data-dataset-id]')];
  const datasetKindOrder = ['data', 'voice', 'speech'];
  const datasetKindLabels = {data: 'Data', voice: 'Voice', speech: 'Speech'};
  const contextFilterDefinitions = [
    {key: 'Region', catalogueKey: 'regions'},
    {key: 'City', catalogueKey: 'cities'},
    {key: 'Operator', catalogueKey: 'operators'},
    {key: 'Vendor', catalogueKey: 'vendors'},
    {key: 'Campaign', catalogueKey: 'campaigns'},
  ];
  const contextFilterSelects = new Map(contextFilterDefinitions.map(({key}) => [
    key, root.querySelector(`[data-scoring-context-filter="${key}"]`),
  ]));
  const scoringConfigElement = root.querySelector('[data-scoring-config]');
  let scoringConfig = {};
  try {
    scoringConfig = JSON.parse(scoringConfigElement?.textContent || '{}');
  } catch {
    scoringConfig = {};
  }
  const mainCities = [...new Set((Array.isArray(scoringConfig.main_cities) ? scoringConfig.main_cities : [])
    .map(value => String(value ?? '').trim()).filter(Boolean))];
  const mainCityIdentities = new Set(mainCities.map(city => city.toLocaleLowerCase()));
  const operatorGroups = (Array.isArray(scoringConfig.operator_groups) ? scoringConfig.operator_groups : [])
    .filter(group => group && typeof group === 'object' && String(group.canonical || '').trim());
  const datasetCatalogues = new Map(datasetOptions.map(option => {
    let catalogue = {};
    try {
      catalogue = JSON.parse(option.dataset.catalogue || '{}');
    } catch {
      catalogue = {};
    }
    return [String(option.querySelector('[data-dataset-id]')?.value || ''), catalogue];
  }));
  const aggregationInputs = [...root.querySelectorAll('[data-aggregation-level]')];
  const baselineInput = root.querySelector('[data-baseline-operator]');
  const calculateButton = root.querySelector('[data-calculate-scoring]');
  const recalculateButton = root.querySelector('[data-recalculate-scoring]');
  const message = root.querySelector('[data-scoring-message]');
  const jobList = root.querySelector('[data-job-list]');
  const resultMeta = root.querySelector('[data-result-meta]');
  const environmentControl = root.querySelector('[data-result-environment-control]');
  const environmentSelect = root.querySelector('[data-result-environment]');
  const chartPane = root.querySelector('[data-result-pane="charts"]');
  const chartOverlay = root.querySelector('[data-scoring-chart-overlay]');
  const chartDialog = root.querySelector('[data-scoring-chart-dialog]');
  const expandedChart = root.querySelector('[data-scoring-expanded-chart]');
  const expandedChartTitle = root.querySelector('[data-scoring-chart-title]');
  const expandedChartMeta = root.querySelector('[data-scoring-chart-meta]');
  const expandedChartClose = root.querySelector('[data-scoring-chart-close]');
  const showKpiValuesToggle = root.querySelector('[data-show-kpi-values]');
  const resultPanes = [...root.querySelectorAll('[data-result-pane]')];
  const resultCache = new Map();
  const contextSelections = new Map();
  const deletedJobIds = new Set();
  const deletingJobIds = new Set();
  let jobs = [];
  let selectedJobId = null;
  let selectedJob = null;
  let selectedEnvironment = null;
  let currentResults = null;
  let chartFocusReturn = null;
  let previousBodyOverflow = '';
  let userSelectedJob = false;
  let refreshInFlight = false;
  let timer = null;

  const valueOf = (object, keys, fallback = '') => {
    if (!object || typeof object !== 'object') return fallback;
    for (const key of keys) {
      if (object[key] !== undefined && object[key] !== null && object[key] !== '') return object[key];
    }
    return fallback;
  };
  const jobIdOf = job => String(valueOf(job, ['id', 'job_id', 'scoring_job_id'], ''));
  const normalizeStatus = job => {
    const raw = String(valueOf(job, ['status', 'state'], 'queued')).toLowerCase();
    if (['done', 'success', 'succeeded', 'complete', 'completed', 'finished', 'ready'].includes(raw)) return 'completed';
    if (['error', 'failure', 'failed', 'cancelled', 'canceled', 'stopped'].includes(raw)) return 'failed';
    if (['processing', 'running', 'in_progress', 'in-progress'].includes(raw)) return 'processing';
    if (['queued', 'pending', 'created'].includes(raw)) return 'queued';
    return raw.replaceAll('_', ' ') || 'queued';
  };
  const isActive = job => ['queued', 'processing'].includes(normalizeStatus(job));
  const isComplete = job => normalizeStatus(job) === 'completed';
  const selectedLevels = () => aggregationInputs.filter(input => input.checked).map(input => input.value);
  const selectedDatasetIds = () => datasetInputs.filter(input => input.checked && !input.closest('[data-dataset-option]')?.hidden).map(input => input.value);

  function uniqueCatalogueValues(values) {
    return [...new Set((Array.isArray(values) ? values : [])
      .map(value => String(value ?? '').trim()).filter(Boolean))];
  }

  function operatorGroupLabels(group) {
    const canonical = String(group.canonical || '').trim();
    return [canonical, ...(Array.isArray(group.aliases) ? group.aliases : [])]
      .map(value => String(value ?? '').trim()).filter(Boolean);
  }

  function contextFilterOptions(key, catalogueValues) {
    if (key !== 'Operator') {
      return catalogueValues.map(value => ({value, label: value, color: ''}))
        .sort((left, right) => left.label.localeCompare(right.label, undefined, {sensitivity: 'base'}));
    }
    const availableByIdentity = new Map(catalogueValues.map(value => [value.toLocaleLowerCase(), value]));
    const mapped = new Set();
    const options = [];
    for (const group of operatorGroups) {
      const canonical = String(group.canonical || '').trim();
      const aliases = operatorGroupLabels(group);
      const matches = aliases.some(alias => availableByIdentity.has(alias.toLocaleLowerCase()));
      if (!matches) continue;
      aliases.forEach(alias => mapped.add(alias.toLocaleLowerCase()));
      options.push({value: canonical, label: canonical, color: String(group.color || '')});
    }
    const unknown = catalogueValues.filter(value => !mapped.has(value.toLocaleLowerCase()))
      .map(value => ({value, label: value, color: ''}))
      .sort((left, right) => left.label.localeCompare(right.label, undefined, {sensitivity: 'base'}));
    return [...options, ...unknown];
  }

  function decorateOperatorOptions(select) {
    const shell = select?.nextElementSibling;
    if (!shell?.matches('.multiselect-shell')) return;
    for (const label of shell.querySelectorAll('.multiselect-option')) {
      const value = label.querySelector('[data-option-value]')?.getAttribute('data-option-value');
      const option = [...(select.options || [])].find(item => item.value === value);
      const color = option?.dataset.operatorColor || '';
      label.classList.toggle('scoring-operator-option', Boolean(color));
      if (color) label.style.setProperty('--scoring-operator-color', color);
      else label.style.removeProperty('--scoring-operator-color');
    }
  }

  function refreshContextFilterOptions() {
    const selectedIds = new Set(selectedDatasetIds());
    for (const {key, catalogueKey} of contextFilterDefinitions) {
      const select = contextFilterSelects.get(key);
      if (!select) continue;
      const selectedValues = new Set([...select.selectedOptions].map(option => option.value).filter(Boolean));
      const rawValues = [];
      for (const datasetId of selectedIds) {
        const values = datasetCatalogues.get(String(datasetId))?.[catalogueKey];
        rawValues.push(...uniqueCatalogueValues(values));
      }
      const nextOptions = contextFilterOptions(key, [...new Set(rawValues)]);
      const presetCities = key === 'City'
        ? nextOptions.filter(option => mainCityIdentities.has(option.value.trim().toLocaleLowerCase())).map(option => option.value) : [];
      const signature = JSON.stringify({
        options: nextOptions.map(option => [option.value, option.label, option.color]),
        presetCities,
      });
      if (select.dataset.scoringCatalogueSignature === signature) continue;
      select.dataset.scoringCatalogueSignature = signature;
      if (key === 'City') {
        select.dataset.multiselectPresetLabel = 'Main Cities';
        select.dataset.multiselectPresetValues = presetCities.join('|');
      }
      select.replaceChildren();
      if (!nextOptions.length) {
        const empty = document.createElement('option');
        empty.value = '';
        empty.disabled = true;
        empty.textContent = 'No values';
        select.append(empty);
      } else {
        for (const entry of nextOptions) {
          const option = document.createElement('option');
          option.value = entry.value;
          option.textContent = entry.label;
          option.selected = selectedValues.has(entry.value);
          if (entry.color) {
            option.dataset.operatorColor = entry.color;
            option.style.color = entry.color;
          }
          select.append(option);
        }
      }
      select.dispatchEvent(new Event('multiselect:options-updated'));
      if (key === 'Operator') decorateOperatorOptions(select);
    }
  }

  function selectedContextFilters() {
    return Object.fromEntries(contextFilterDefinitions.map(({key}) => {
      const select = contextFilterSelects.get(key);
      const values = select ? [...select.selectedOptions]
        .filter(option => !option.disabled && option.value)
        .map(option => String(option.value)) : [];
      return [key, values];
    }));
  }

  function contextFilterSummary(job) {
    const filters = job?.context_filters && typeof job.context_filters === 'object'
      ? job.context_filters : {};
    const entries = contextFilterDefinitions.flatMap(({key}) => {
      const values = filters[key] ?? filters[key.toLowerCase()];
      const normalized = uniqueCatalogueValues(Array.isArray(values) ? values : (values ? [values] : []));
      return normalized.length ? [`${key}: ${normalized.join(', ')}`] : [];
    });
    return entries.length ? entries.join(' · ') : 'All values';
  }

  function setMessage(text, kind = '') {
    if (!message) return;
    message.textContent = text;
    message.dataset.kind = kind;
  }

  function updateSelection() {
    refreshContextFilterOptions();
    const selectedCount = selectedDatasetIds().length;
    const visibleCount = datasetOptions.filter(option => !option.hidden).length;
    const missingKinds = [];
    const unavailableKinds = [];
    for (const kind of datasetKindOrder) {
      const kindOptions = datasetOptions.filter(option => !option.hidden && String(option.dataset.datasetKind || '').toLowerCase() === kind);
      const kindSelected = kindOptions.filter(option => option.querySelector('[data-dataset-id]')?.checked).length;
      const count = root.querySelector(`[data-kind-count="${kind}"]`);
      const empty = root.querySelector(`[data-dataset-group="${kind}"] [data-kind-empty]`);
      if (count) count.textContent = `${kindOptions.length} available${kindSelected ? ` · ${kindSelected} selected` : ''}`;
      if (empty) {
        empty.hidden = kindOptions.length > 0;
        empty.textContent = `No ready ${datasetKindLabels[kind]} CDR datasets are available for this NR Mode.`;
      }
      if (!kindSelected) missingKinds.push(kind);
      if (!kindOptions.length) unavailableKinds.push(kind);
    }
    const selectedBadge = root.querySelector('[data-selected-count]');
    const visibleBadge = root.querySelector('[data-visible-count]');
    if (selectedBadge) selectedBadge.textContent = `${selectedCount} CDR${selectedCount === 1 ? '' : 's'} selected`;
    if (visibleBadge) visibleBadge.textContent = `${visibleCount} available`;
    const configurationError = root.dataset.configurationError || '';
    const ready = missingKinds.length === 0 && !configurationError;
    calculateButton.disabled = !ready;
    recalculateButton.disabled = !ready;
    if (configurationError) {
      setMessage(`${configurationError} Open Workspace Config → Scoring KPI Configuration.`, 'error');
    } else if (!ready) {
      const missingLabels = missingKinds.map(kind => datasetKindLabels[kind]);
      const unavailableLabels = unavailableKinds.map(kind => datasetKindLabels[kind]);
      const status = unavailableLabels.length
        ? `No ready ${unavailableLabels.join(', ')} CDR datasets are available for this NR Mode. `
        : '';
      setMessage(`${status}Select at least one dataset from each CDR type: ${missingLabels.join(', ')}.`);
    } else if (message.dataset.kind !== 'error' && message.dataset.kind !== 'success') {
      setMessage(`${selectedCount} CDR${selectedCount === 1 ? '' : 's'} selected across Data, Voice and Speech. Operator aggregation is included automatically.`);
    }
  }

  function selectLatestDatasetForEachKind() {
    for (const input of datasetInputs) input.checked = false;
    for (const kind of datasetKindOrder) {
      const candidates = datasetOptions.filter(option => !option.hidden && String(option.dataset.datasetKind || '').toLowerCase() === kind);
      candidates.sort((left, right) => {
        const leftUploaded = Date.parse(left.dataset.uploadedAt || '');
        const rightUploaded = Date.parse(right.dataset.uploadedAt || '');
        const leftHasUploadDate = Number.isFinite(leftUploaded);
        const rightHasUploadDate = Number.isFinite(rightUploaded);
        if (leftHasUploadDate && rightHasUploadDate && leftUploaded !== rightUploaded) return rightUploaded - leftUploaded;
        if (leftHasUploadDate !== rightHasUploadDate) return leftHasUploadDate ? -1 : 1;
        const leftId = Number(left.querySelector('[data-dataset-id]')?.value || 0);
        const rightId = Number(right.querySelector('[data-dataset-id]')?.value || 0);
        return rightId - leftId;
      });
      const newest = candidates[0]?.querySelector('[data-dataset-id]');
      if (newest) newest.checked = true;
    }
  }

  function applyNrFilter(selectLatest = false) {
    const mode = nrFilter.value;
    for (const option of datasetOptions) {
      const matches = !mode || option.dataset.nrMode === mode;
      option.hidden = !matches;
      if (!matches) {
        const checkbox = option.querySelector('[data-dataset-id]');
        if (checkbox) checkbox.checked = false;
      }
    }
    if (selectLatest) selectLatestDatasetForEachKind();
    updateSelection();
  }

  function formatDate(value) {
    if (!value) return 'Date unavailable';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
  }

  function jobSummary(job) {
    const names = valueOf(job, ['dataset_names', 'cdr_names', 'campaigns'], null);
    if (Array.isArray(names) && names.length) return names.join(', ');
    const ids = valueOf(job, ['dataset_ids', 'cdr_ids'], []);
    const count = Array.isArray(ids) ? ids.length : Number(valueOf(job, ['dataset_count'], 0));
    const campaign = valueOf(job, ['campaign', 'campaign_name', 'campaigns'], '');
    return [campaign || `${count || 'Selected'} CDR${count === 1 ? '' : 's'}`].filter(Boolean).join('');
  }

  function campaignLabels(value) {
    const values = Array.isArray(value) ? value : [value];
    return values.flatMap(item => {
      if (typeof item === 'string') return item.trim() ? [item.trim()] : [];
      if (!item || typeof item !== 'object') return [];
      return campaignLabels(firstValue(item, ['campaigns', 'campaign'], null));
    });
  }

  function jobCampaigns(job) {
    let campaigns = campaignLabels(job?.campaigns);
    if (!campaigns.length) campaigns = campaignLabels(valueOf(job, ['campaign', 'campaign_name'], null));
    if (!campaigns.length) {
      const metadata = job?.source_metadata;
      const entries = Array.isArray(metadata) ? metadata : (metadata && typeof metadata === 'object' ? Object.values(metadata) : []);
      campaigns = entries.flatMap(entry => campaignLabels(entry));
    }
    const unique = [...new Set(campaigns)];
    return unique.length ? unique : ['Unspecified'];
  }

  function jobLevels(job) {
    const levels = valueOf(job, ['aggregation_levels', 'levels'], []);
    return Array.isArray(levels) ? levels.join(' · ') : String(levels || 'Operator');
  }

  function progressValue(job) {
    const raw = Number(valueOf(job, ['progress', 'progress_percent', 'percentage'], 0));
    if (!Number.isFinite(raw)) return 0;
    return Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw));
  }

  function sortedJobs(records) {
    return [...records].sort((left, right) => {
      const leftDate = new Date(valueOf(left, ['created_at', 'submitted_at', 'started_at'], 0)).getTime() || 0;
      const rightDate = new Date(valueOf(right, ['created_at', 'submitted_at', 'started_at'], 0)).getTime() || 0;
      return rightDate - leftDate;
    });
  }

  function renderJobs() {
    const ordered = sortedJobs(jobs);
    const countBadge = root.querySelector('[data-job-count]');
    if (countBadge) countBadge.textContent = `${ordered.length} job${ordered.length === 1 ? '' : 's'}`;
    jobList.replaceChildren();
    if (!ordered.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No scoring jobs have been run in this workspace.';
      jobList.append(empty);
      return;
    }
    for (const job of ordered) {
      const id = jobIdOf(job);
      const status = normalizeStatus(job);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'scoring-job-item';
      button.dataset.jobId = id;
      button.setAttribute('aria-current', String(id === selectedJobId));
      const top = document.createElement('span');
      top.className = 'scoring-job-item-top';
      const title = document.createElement('strong');
      title.textContent = jobSummary(job);
      title.title = title.textContent;
      const statusBadge = document.createElement('span');
      statusBadge.className = 'scoring-status';
      statusBadge.dataset.status = status;
      statusBadge.textContent = status;
      top.append(title, statusBadge);
      button.append(top);
      const meta = document.createElement('span');
      meta.className = 'scoring-job-meta';
      const mode = valueOf(job, ['nr_mode'], 'All NR Modes');
      const baseline = valueOf(job, ['baseline_operator'], 'EE');
      meta.textContent = `${formatDate(valueOf(job, ['created_at', 'submitted_at', 'started_at'], ''))} · ${jobLevels(job)} · ${mode} · GAP baseline ${baseline}`;
      button.append(meta);
      const campaignMeta = document.createElement('span');
      campaignMeta.className = 'scoring-job-meta';
      campaignMeta.textContent = `Campaigns: ${jobCampaigns(job).join(', ')}`;
      button.append(campaignMeta);
      const filterMeta = document.createElement('span');
      filterMeta.className = 'scoring-job-meta';
      filterMeta.textContent = `Context filters: ${contextFilterSummary(job)}`;
      button.append(filterMeta);
      if (isActive(job)) {
        const progress = document.createElement('span');
        progress.className = 'scoring-job-progress';
        progress.setAttribute('aria-label', `Job ${progressValue(job)} percent complete`);
        const bar = document.createElement('span');
        bar.style.width = `${progressValue(job)}%`;
        progress.append(bar);
        button.append(progress);
      }
      const error = valueOf(job, ['error', 'error_message', 'last_error'], '');
      if (status === 'failed' && error) {
        const detail = document.createElement('span');
        detail.className = 'scoring-job-meta';
        detail.textContent = error;
        button.append(detail);
      }
      const row = document.createElement('div');
      row.className = 'scoring-job-row';
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'scoring-job-delete';
      remove.dataset.deleteJobId = id;
      remove.textContent = '×';
      remove.title = 'Delete scoring job and saved results';
      remove.setAttribute('aria-label', `Delete scoring job ${id}`);
      remove.disabled = deletingJobIds.has(id);
      row.append(button, remove);
      jobList.append(row);
    }
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {Accept: 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {})},
      ...options,
    });
    const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
    if (!response.ok) throw new Error(body?.detail || body?.error || `Scoring request failed (HTTP ${response.status}).`);
    return body || {};
  }

  function setExportLinks(jobId, enabled) {
    for (const [kind, selector] of [['scoring', '[data-export-scoring]'], ['gap', '[data-export-gap]'], ['ppt', '[data-export-ppt]']]) {
      const link = root.querySelector(selector);
      link.hidden = !enabled;
      link.href = enabled ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}` : '#';
    }
  }

  function normalizeRows(data) {
    if (Array.isArray(data)) return data.filter(row => row && typeof row === 'object');
    if (data && Array.isArray(data.rows)) return data.rows.filter(row => row && typeof row === 'object');
    if (data && Array.isArray(data.data)) return data.data.filter(row => row && typeof row === 'object');
    if (data && Array.isArray(data.tables)) return data.tables.flatMap(table => normalizeRows(table));
    return [];
  }

  function humanizeKey(key) {
    return String(key).replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
  }

  function displayValue(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'number' && Number.isFinite(value)) return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, {maximumFractionDigits: 3});
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function renderTable(pane, source, emptyCopy) {
    pane.replaceChildren();
    const rows = normalizeRows(source);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = emptyCopy;
      pane.append(empty);
      return;
    }
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-table-wrap';
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    for (const column of columns) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = humanizeKey(column);
      headerRow.append(th);
    }
    thead.append(headerRow);
    const tbody = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr');
      for (const column of columns) {
        const td = document.createElement('td');
        const value = row[column];
        td.textContent = displayValue(value);
        if (typeof value === 'number' && Number.isFinite(value)) td.dataset.numeric = 'true';
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(thead, tbody);
    wrapper.append(table);
    pane.append(wrapper);
  }

  function firstValue(object, names, fallback = null) {
    if (!object || typeof object !== 'object') return fallback;
    for (const name of names) {
      if (Object.prototype.hasOwnProperty.call(object, name) && object[name] !== undefined && object[name] !== '') return object[name];
      const key = Object.keys(object).find(candidate => candidate.toLowerCase() === name.toLowerCase());
      if (key && object[key] !== undefined && object[key] !== '') return object[key];
    }
    return fallback;
  }

  function comparisonIdentity(table, kind) {
    const context = table?.context && typeof table.context === 'object'
      ? Object.fromEntries(Object.entries(table.context).sort(([left], [right]) => left.localeCompare(right)))
      : {};
    return JSON.stringify([kind, table?.title || '', context, table?.operator || '']);
  }

  function comparisonLabel(table, kind) {
    const context = contextLabel(table?.context);
    if (kind === 'gap' && table?.operator) {
      const operator = operatorPresentation(table, table.operator).label;
      const baseline = operatorPresentation(table, table.baseline_operator || '').label;
      return `${context || 'Overall scope'} · ${operator} vs ${baseline}`;
    }
    return String(table?.title || context || 'Overall scope');
  }

  function contextLabel(context) {
    if (!context || typeof context !== 'object') return '';
    const preferred = ['campaign', 'region', 'city', 'vendor', 'dataset_type', 'environment'];
    const entries = preferred.filter(key => context[key] !== null && context[key] !== undefined && context[key] !== '')
      .map(key => [key, context[key]]);
    for (const [key, value] of Object.entries(context)) {
      if (!preferred.includes(key) && value !== null && value !== undefined && value !== '') entries.push([key, value]);
    }
    return entries.map(([key, value]) => `${humanizeKey(key)}: ${value}`).join(' · ');
  }

  function appendContextHeader(pane, table, kind, titlePrefix = '') {
    const heading = document.createElement('h4');
    heading.className = 'scoring-context-heading';
    const contextTitle = contextLabel(table?.context);
    heading.textContent = titlePrefix
      ? [titlePrefix, contextTitle].filter(Boolean).join(' · ')
      : comparisonLabel(table, kind);
    pane.append(heading);

    const context = table?.context && typeof table.context === 'object' ? table.context : {};
    const preferred = ['campaign', 'region', 'city', 'vendor', 'dataset_type', 'environment'];
    const entries = preferred.filter(key => context[key] !== null && context[key] !== undefined && context[key] !== '')
      .map(key => [key, context[key]]);
    for (const [key, value] of Object.entries(context)) {
      if (!preferred.includes(key) && value !== null && value !== undefined && value !== '') entries.push([key, value]);
    }
    if (entries.length) {
      const chips = document.createElement('div');
      chips.className = 'scoring-context-chips';
      for (const [key, value] of entries) {
        const chip = document.createElement('span');
        chip.className = 'scoring-context-chip';
        chip.textContent = `${humanizeKey(key)}: ${value}`;
        chips.append(chip);
      }
      pane.append(chips);
    }
    const note = table?.coverage_note ?? table?.note ?? '';
    if (note) {
      const coverage = document.createElement('p');
      coverage.className = 'scoring-context-note';
      coverage.textContent = typeof note === 'string' ? note : displayValue(note);
      pane.append(coverage);
    }
  }

  function appendComparisonSelector(pane, tables, kind, contextSource = 'tables') {
    const savedSelection = contextSelections.get(kind);
    let selected = tables.find(table => comparisonIdentity(table, kind) === savedSelection) || tables[0];
    if (tables.length > 1) {
      const controls = document.createElement('div');
      controls.className = 'scoring-comparison-controls';
      const label = document.createElement('label');
      label.textContent = kind === 'gap' ? 'Comparison context and operator' : 'Comparison context';
      const select = document.createElement('select');
      select.dataset.comparisonContext = '';
      select.dataset.contextKind = kind;
      select.dataset.contextSource = contextSource;
      for (const [index, table] of tables.entries()) {
        const option = document.createElement('option');
        option.value = String(index);
        option.textContent = comparisonLabel(table, kind);
        option.dataset.contextIdentity = comparisonIdentity(table, kind);
        option.selected = table === selected;
        select.append(option);
      }
      label.append(select);
      controls.append(label);
      pane.append(controls);
    }
    if (selected) contextSelections.set(kind, comparisonIdentity(selected, kind));
    return selected;
  }

  function operatorValue(values, operator) {
    return firstValue(values, [operator], null);
  }

  function isReferenceOperator(table, rawName) {
    const baseline = String(table?.baseline_operator || '');
    return Boolean(baseline && String(rawName).toLowerCase() === baseline.toLowerCase());
  }

  function markReferenceHeader(header) {
    header.classList.add('scoring-reference-header');
    const label = header.textContent.trim();
    header.setAttribute('aria-label', `${label}, reference operator`);
    header.title = `${label} is the reference operator`;
  }

  function operatorPresentation(operatorStyles, rawName) {
    const styles = operatorStyles?.operator_styles && typeof operatorStyles.operator_styles === 'object'
      ? operatorStyles.operator_styles
      : operatorStyles;
    const configured = firstValue(styles, [rawName], null);
    if (!configured || typeof configured !== 'object') return {label: String(rawName), color: '', position: null};
    const position = Number(firstValue(configured, ['position'], Number.NaN));
    return {
      label: String(firstValue(configured, ['label', 'canonical'], rawName)),
      color: safeHexColor(firstValue(configured, ['color'], '')),
      position: Number.isFinite(position) ? position : null,
    };
  }

  function readableTextColor(background) {
    const color = safeHexColor(background);
    if (!color) return '';
    const red = Number.parseInt(color.slice(1, 3), 16);
    const green = Number.parseInt(color.slice(3, 5), 16);
    const blue = Number.parseInt(color.slice(5, 7), 16);
    const luminance = (red * 299 + green * 587 + blue * 114) / 1000;
    return luminance > 155 ? '#203744' : '#ffffff';
  }

  function formatMatrixNumber(value, signed = false) {
    if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return 'N/A';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'N/A';
    if (signed && numeric > 0) return `+${numeric.toFixed(2)}`;
    if (signed && numeric < 0) return `−${Math.abs(numeric).toFixed(2)}`;
    return numeric.toFixed(2);
  }

  function formatScoreCell(cell) {
    if (!cell || typeof cell !== 'object') return {text: 'N/A', complete: false};
    const points = firstValue(cell, ['points', 'weighted_points', 'weighted_score'], null);
    const complete = firstValue(cell, ['complete', 'complete_coverage'], false) === true;
    if (points === null || points === undefined || (typeof points === 'string' && points.trim() === '')) return {text: 'N/A', complete: false};
    const numeric = Number(points);
    if (!Number.isFinite(numeric)) return {text: 'N/A', complete: false};
    return {text: `${numeric.toFixed(2)}${complete ? '' : '*'}`, complete};
  }

  function formatRawKpiValue(value) {
    if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return 'N/A';
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric.toLocaleString(undefined, {maximumFractionDigits: 3});
    return String(value);
  }

  function safeHexColor(value) {
    const color = String(value ?? '').trim();
    return /^#[0-9a-f]{6}$/i.test(color) ? color : '';
  }

  function appendThresholdLegend(pane, legend) {
    if (!Array.isArray(legend) || !legend.length) return;
    const container = document.createElement('div');
    container.className = 'scoring-threshold-legend';
    const title = document.createElement('strong');
    title.textContent = 'KPI score bands';
    container.append(title);
    for (const entry of legend) {
      const color = safeHexColor(entry?.color);
      const label = String(entry?.band || entry?.label || 'Not classified');
      const item = document.createElement('span');
      item.className = 'scoring-legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'scoring-legend-swatch';
      if (color) swatch.style.backgroundColor = color;
      swatch.setAttribute('aria-hidden', 'true');
      const copy = document.createElement('span');
      copy.className = 'scoring-legend-copy';
      const band = document.createElement('strong');
      band.textContent = label;
      copy.append(band);
      const definition = entry?.definition ?? entry?.description ?? entry?.range ?? '';
      if (definition) {
        const detail = document.createElement('small');
        detail.textContent = String(definition);
        copy.append(detail);
        item.title = String(definition);
      }
      item.append(swatch, copy);
      container.append(item);
    }
    pane.append(container);
  }

  function appendScoringGapScale(pane, tableData) {
    const maximum = Number(tableData?.gap_scale_max);
    if (!Number.isFinite(maximum) || maximum <= 0) return;
    const colors = tableData?.gap_scale_colors && typeof tableData.gap_scale_colors === 'object' ? tableData.gap_scale_colors : {};
    const negativeColor = safeHexColor(firstValue(colors, ['loss', 'negative'], ''));
    const neutralColor = safeHexColor(firstValue(colors, ['zero', 'neutral'], ''));
    const positiveColor = safeHexColor(firstValue(colors, ['advantage', 'positive'], ''));
    const container = document.createElement('div');
    container.className = 'scoring-gap-scale';
    const label = document.createElement('span');
    label.textContent = 'GAP color scale';
    if (negativeColor && neutralColor && positiveColor) {
      const bar = document.createElement('span');
      bar.className = 'scoring-gap-scale-bar';
      bar.style.background = `linear-gradient(90deg, ${negativeColor}, ${neutralColor} 50%, ${positiveColor})`;
      bar.setAttribute('aria-hidden', 'true');
      container.append(label, bar);
    } else {
      container.append(label);
    }
    const scale = document.createElement('span');
    scale.textContent = `Context scale: −${maximum.toFixed(2)} (operator trails) · 0 · +${maximum.toFixed(2)} (operator leads)`;
    container.append(scale);
    pane.append(container);
  }

  function appendPriorityGapScale(pane, tableData, rows) {
    const maximum = Number(tableData?.gap_scale_max);
    if (!Number.isFinite(maximum) || maximum <= 0 || !rows.length) return;
    const colors = tableData?.gap_scale_colors && typeof tableData.gap_scale_colors === 'object' ? tableData.gap_scale_colors : {};
    const neutralColor = safeHexColor(firstValue(colors, ['zero', 'neutral'], ''));
    const positiveColor = safeHexColor(firstValue(colors, ['advantage', 'positive'], ''));
    const negativeColor = safeHexColor(firstValue(colors, ['loss', 'negative'], ''));
    const container = document.createElement('div');
    container.className = 'scoring-gap-scale scoring-gap-scale-positive';
    const label = document.createElement('span');
    label.textContent = 'GAP color scale';
    container.append(label);
    if (neutralColor && positiveColor && negativeColor) {
      const bar = document.createElement('span');
      bar.className = 'scoring-gap-scale-bar';
      bar.style.background = `linear-gradient(90deg, ${negativeColor}, ${neutralColor} 50%, ${positiveColor})`;
      bar.setAttribute('aria-hidden', 'true');
      container.append(bar);
    }
    const scale = document.createElement('span');
    scale.textContent = `−${maximum.toFixed(2)} (operator trails) · 0 · +${maximum.toFixed(2)} (operator leads)`;
    container.append(scale);
    pane.append(container);
  }

  function addMatrixScoreCell(row, cell, className = '', isTotal = false) {
    const td = document.createElement('td');
    td.dataset.numeric = 'true';
    td.dataset.column = 'score';
    const formatted = formatScoreCell(cell);
    td.textContent = formatted.text;
    if (className) td.className = className;
    const band = firstValue(cell, ['threshold_band', 'band'], '');
    const color = safeHexColor(firstValue(cell, ['color', 'threshold_color'], ''));
    if (!isTotal && color) td.style.backgroundColor = color;
    if (isTotal && !formatted.complete) {
      td.classList.add('scoring-total-partial');
      td.style.backgroundColor = '#e6e9ea';
    }
    const score = firstValue(cell, ['score', 'score_fraction'], null);
    const scoreNumber = score === null || score === undefined || (typeof score === 'string' && score.trim() === '') ? Number.NaN : Number(score);
    const scoreLabel = Number.isFinite(scoreNumber)
      ? `KPI score ${((scoreNumber <= 1 ? scoreNumber * 100 : scoreNumber)).toFixed(2)}%.`
      : '';
    const bandLabel = band ? `Band: ${band}. ` : '';
    if (!formatted.complete) {
      td.title = isTotal
        ? 'Partial total: KPI or environment coverage is incomplete. This is not a full score.'
        : `Partial score: expected KPI or environment coverage is incomplete. This is not a full score. ${bandLabel}${scoreLabel}`.trim();
    } else if (band || scoreLabel) {
      td.title = `${bandLabel}${scoreLabel}`.trim();
    }
    row.append(td);
  }

  function addMatrixGapCell(row, value, color = '') {
    const td = document.createElement('td');
    td.dataset.numeric = 'true';
    td.dataset.column = 'gap';
    td.textContent = formatMatrixNumber(value, true);
    const safeColor = safeHexColor(color);
    if (safeColor) td.style.backgroundColor = safeColor;
    if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) {
      const numeric = Number(value);
      if (numeric > 0) {
        td.className = 'scoring-gap-gain';
        td.title = 'Positive GAP: the compared operator scores higher than the baseline for this KPI.';
      } else if (numeric < 0) {
        td.className = 'scoring-gap-loss';
        td.title = 'Negative GAP: the compared operator scores lower than the baseline for this KPI.';
      }
    }
    row.append(td);
  }

  function appendMatrixTable(pane, tableData) {
    const rows = Array.isArray(tableData?.rows) ? tableData.rows : [];
    const operators = Array.isArray(tableData?.operators) ? tableData.operators.map(String) : [];
    const baseline = String(tableData?.baseline_operator || '');
    const baselineLabel = operatorPresentation(tableData, baseline).label;
    const nonBaseline = operators.filter(operator => !baseline || operator.toLowerCase() !== baseline.toLowerCase());
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table';
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const title of ['Category', 'KPI', 'Score weight (%)', 'Max score']) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.rowSpan = 2;
      th.dataset.column = title === 'Category' ? 'category' : (title === 'KPI' ? 'kpi' : (title === 'Score weight (%)' ? 'weight' : 'maximum'));
      th.textContent = title;
      if (title === 'Score weight (%)') th.className = 'scoring-weight-header';
      if (title === 'Max score') th.className = 'scoring-maximum-header';
      header.append(th);
    }
    const showKpiValues = Boolean(showKpiValuesToggle?.checked);
    if (showKpiValues && operators.length) {
      const group = document.createElement('th');
      group.scope = 'colgroup';
      group.colSpan = operators.length;
      group.className = 'scoring-column-group scoring-kpi-value-group';
      group.textContent = 'KPI Value';
      header.append(group);
    }
    if (operators.length) {
      const group = document.createElement('th');
      group.scope = 'colgroup';
      group.colSpan = operators.length;
      group.className = 'scoring-column-group scoring-score-group';
      group.textContent = 'Score';
      header.append(group);
    }
    if (nonBaseline.length) {
      const group = document.createElement('th');
      group.scope = 'colgroup';
      group.colSpan = nonBaseline.length;
      group.className = 'scoring-column-group scoring-gap-group';
      group.textContent = 'GAP';
      header.append(group);
    }
    const operatorHeader = document.createElement('tr');
    if (showKpiValues) {
      for (const operator of operators) {
        const presentation = operatorPresentation(tableData, operator);
        const th = document.createElement('th');
        th.scope = 'col';
        th.className = 'scoring-kpi-value-header';
        th.dataset.column = 'kpi-value';
        th.textContent = presentation.label;
        th.title = `Raw KPI measurement for ${presentation.label} (${operator}); units are shown when provided by the KPI definition.`;
        if (presentation.color) {
          th.style.backgroundColor = presentation.color;
          th.style.color = readableTextColor(presentation.color);
        }
        if (isReferenceOperator(tableData, operator)) markReferenceHeader(th);
        operatorHeader.append(th);
      }
    }
    operators.forEach((operator, index) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.dataset.column = 'score';
      const presentation = operatorPresentation(tableData, operator);
      th.textContent = presentation.label;
      const operatorTone = operator.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      th.className = `scoring-operator-header scoring-tone-${index % 5} scoring-operator-${operatorTone}`;
      th.title = `${operator} weighted KPI points`;
      if (presentation.color) {
        th.style.backgroundColor = presentation.color;
        th.style.color = readableTextColor(presentation.color);
        th.style.setProperty('--operator-accent', presentation.color);
      }
      if (isReferenceOperator(tableData, operator)) markReferenceHeader(th);
      operatorHeader.append(th);
    });
    nonBaseline.forEach(operator => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.className = 'scoring-gap-header';
      th.dataset.column = 'gap';
      const operatorLabel = operatorPresentation(tableData, operator).label;
      th.textContent = `${operatorLabel} − ${baselineLabel}`;
      th.title = `${operator} weighted points minus baseline ${baseline} weighted points`;
      operatorHeader.append(th);
    });
    thead.append(header, operatorHeader);

    const tbody = document.createElement('tbody');
    const categoryRuns = new Map();
    for (let index = 0; index < rows.length; index += 1) {
      const category = String(rows[index]?.category || 'Other');
      if (index > 0 && String(rows[index - 1]?.category || 'Other') === category) continue;
      let span = 1;
      while (index + span < rows.length && String(rows[index + span]?.category || 'Other') === category) span += 1;
      categoryRuns.set(index, {category, span});
    }
    rows.forEach((item, index) => {
      const tr = document.createElement('tr');
      const run = categoryRuns.get(index);
      if (run) {
        const category = document.createElement('td');
        category.className = 'scoring-category-cell';
        category.rowSpan = run.span;
        category.textContent = run.category;
        category.dataset.column = 'category';
        tr.append(category);
      }
      const kpi = document.createElement('td');
      kpi.dataset.column = 'kpi';
      kpi.textContent = String(item?.kpi || item?.kpi_code || 'N/A');
      kpi.title = String(item?.kpi_code || item?.kpi || '');
      tr.append(kpi);

      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(item?.weight_percent);
      tr.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(item?.max_points);
      tr.append(maximum);

      const values = item?.values && typeof item.values === 'object' ? item.values : {};
      if (showKpiValues) {
        for (const operator of operators) {
          const cell = document.createElement('td');
          cell.dataset.column = 'kpi-value';
          const operatorCell = operatorValue(values, operator);
          const rawValue = operatorCell && typeof operatorCell === 'object' ? firstValue(operatorCell, ['value', 'raw_value', 'kpi_value'], null) : null;
          const presentation = operatorPresentation(tableData, operator);
          const unit = firstValue(item, ['unit', 'units', 'measurement_unit'], '');
          cell.className = 'scoring-kpi-value-cell';
          cell.textContent = formatRawKpiValue(rawValue);
          cell.dataset.numeric = rawValue !== null && rawValue !== undefined && String(rawValue).trim() !== '' && Number.isFinite(Number(rawValue)) ? 'true' : 'false';
          cell.title = `Raw ${item?.kpi || item?.kpi_code || 'KPI'} measurement for ${presentation.label}${unit ? ` (${unit})` : ''}: ${formatRawKpiValue(rawValue)}`;
          tr.append(cell);
        }
      }
      for (const [operatorIndex, operator] of operators.entries()) {
        addMatrixScoreCell(tr, operatorValue(values, operator), `scoring-tone-${operatorIndex % 5}`);
      }
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      for (const operator of nonBaseline) addMatrixGapCell(tr, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''));
      tbody.append(tr);
    });

    table.append(thead, tbody);
    const total = tableData?.total;
    if (total && typeof total === 'object') {
      const tfoot = document.createElement('tfoot');
      const row = document.createElement('tr');
      const category = document.createElement('th');
      category.scope = 'row';
      category.dataset.column = 'category';
      category.textContent = 'Total';
      row.append(category);
      const label = document.createElement('td');
      label.dataset.column = 'kpi';
      label.textContent = 'Weighted score';
      row.append(label);
      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(firstValue(total, ['weight_percent'], 100));
      row.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(firstValue(total, ['max_points'], null));
      row.append(maximum);
      const values = total.values && typeof total.values === 'object' ? total.values : {};
      if (showKpiValues) {
        operators.forEach(() => {
          const cell = document.createElement('td');
          cell.className = 'scoring-kpi-value-cell';
          cell.dataset.column = 'kpi-value';
          cell.textContent = 'N/A';
          cell.title = 'A single raw KPI measurement does not apply to the weighted total.';
          row.append(cell);
        });
      }
      operators.forEach(operator => addMatrixScoreCell(row, operatorValue(values, operator), '', true));
      const gaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
      const gapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      nonBaseline.forEach(operator => addMatrixGapCell(row, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], '')));
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No KPI rows are available for this comparison context.';
      pane.append(empty);
    }
  }

  function renderScoringViews(pane, tables, thresholdLegend = []) {
    pane.replaceChildren();
    if (!tables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No scoring comparison tables are available for this job.';
      pane.append(empty);
      return;
    }
    const selected = appendComparisonSelector(pane, tables, 'score');
    appendContextHeader(pane, selected, 'score');
    appendThresholdLegend(pane, thresholdLegend.length ? thresholdLegend : selected?.threshold_legend);
    appendScoringGapScale(pane, selected);
    appendMatrixTable(pane, selected);
  }

  function renderGapViews(pane, tables) {
    pane.replaceChildren();
    if (!tables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No GAP comparison tables are available for this job.';
      pane.append(empty);
      return;
    }
    const selected = appendComparisonSelector(pane, tables, 'gap');
    appendContextHeader(pane, selected, 'gap');
    const baselineRaw = String(selected?.baseline_operator || 'the baseline');
    const operatorRaw = String(selected?.operator || 'this operator');
    const baseline = operatorPresentation(selected, baselineRaw).label;
    const operator = operatorPresentation(selected, operatorRaw).label;
    const rows = (Array.isArray(selected?.rows) ? selected.rows : [])
      .filter(row => row?.gap_points !== null && row?.gap_points !== undefined && String(row.gap_points).trim() !== '' && Number.isFinite(Number(row.gap_points)))
      .sort((left, right) => Math.abs(Number(right.gap_points)) - Math.abs(Number(left.gap_points)));
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = `No comparable signed KPI GAPs were found for ${operator} against ${baseline} in this comparison context.`;
      pane.append(empty);
      return;
    }
    appendPriorityGapScale(pane, selected, rows);
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-priority-table';
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const [title, key] of [['Category', 'category'], ['KPI', 'kpi'], [`GAP (${operator} − ${baseline})`, 'gap'], ['Type of KPI', 'type']]) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = title;
      th.dataset.column = key;
      if (key === 'gap') th.className = 'scoring-gap-header';
      header.append(th);
    }
    thead.append(header);
    const tbody = document.createElement('tbody');
    for (const item of rows) {
      const row = document.createElement('tr');
      for (const [value, key] of [[item.category, 'category'], [item.kpi || item.kpi_code, 'kpi'], [item.gap_points, 'gap'], [item.kpi_type, 'type']]) {
        const cell = document.createElement('td');
        cell.dataset.column = key;
        if (key === 'gap') {
          cell.dataset.numeric = 'true';
          cell.textContent = formatMatrixNumber(value, true);
          cell.title = 'Signed GAP: compared operator weighted points minus baseline weighted points. Positive means the compared operator leads.';
          const color = safeHexColor(item?.gap_color);
          if (color) cell.style.backgroundColor = color;
          if (Number(value) > 0) cell.classList.add('scoring-gap-gain');
          if (Number(value) < 0) cell.classList.add('scoring-gap-loss');
        } else {
          const normalizedType = String(value ?? '').toLowerCase();
          cell.textContent = key === 'type' && (value === null || value === undefined || value === '' || normalizedType === 'unknown')
            ? 'Not classified'
            : (value === null || value === undefined || value === '' ? 'N/A' : String(value));
          if (key === 'type' && normalizedType === 'reliable') cell.dataset.kpiType = 'reliable';
          if (key === 'kpi') cell.title = String(item.kpi_code || item.kpi || '');
        }
        row.append(cell);
      }
      tbody.append(row);
    }
    table.append(thead, tbody);
    wrapper.append(table);
    pane.append(wrapper);
    if (selected?.total_gap_points !== null && selected?.total_gap_points !== undefined) {
      const summary = document.createElement('p');
      summary.className = 'scoring-context-note';
      summary.textContent = `Total signed GAP (${operator} − ${baseline}): ${formatMatrixNumber(selected.total_gap_points, true)} points.`;
      pane.append(summary);
    }
  }

  function renderGapSummaryViews(pane, tables) {
    pane.replaceChildren();
    if (!tables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No GAP summary tables are available for this environment.';
      pane.append(empty);
      return;
    }
    const selected = appendComparisonSelector(pane, tables, 'gap-summary');
    if (!selected) return;

    const baselineRaw = String(selected.baseline_operator || '');
    const baseline = operatorPresentation(selected, baselineRaw || 'the reference operator').label;
    const operators = (Array.isArray(selected.operators) ? selected.operators : [])
      .map(String)
      .filter(operator => operator.toLowerCase() !== baselineRaw.toLowerCase());
    const comparisonStateKey = `gap-summary-operator:${comparisonIdentity(selected, 'gap-summary')}:${baselineRaw}`;
    let comparison = contextSelections.get(comparisonStateKey) || 'all';
    const selectedOperator = comparison.startsWith('operator:') ? comparison.slice('operator:'.length) : null;
    if (selectedOperator && !operators.includes(selectedOperator)) comparison = 'all';
    contextSelections.set(comparisonStateKey, comparison);

    const controls = document.createElement('div');
    controls.className = 'scoring-comparison-controls scoring-gap-comparison-controls';
    const label = document.createElement('label');
    label.textContent = 'Operator comparison';
    const select = document.createElement('select');
    select.dataset.gapSummaryOperator = '';
    select.dataset.gapSummaryStateKey = comparisonStateKey;
    select.setAttribute('aria-label', 'Choose all operators or one operator to compare with the reference');
    const allOption = document.createElement('option');
    allOption.value = 'all';
    allOption.textContent = `All vs ${baseline}`;
    allOption.selected = comparison === 'all';
    select.append(allOption);
    for (const operator of operators) {
      const presentation = operatorPresentation(selected, operator);
      const option = document.createElement('option');
      option.value = `operator:${operator}`;
      option.textContent = `${presentation.label} vs ${baseline}`;
      option.selected = comparison === option.value;
      select.append(option);
    }
    label.append(select);
    controls.append(label);
    pane.append(controls);

    appendContextHeader(pane, selected, 'gap-summary');
    const gapNote = document.createElement('p');
    gapNote.className = 'scoring-context-note';
    gapNote.textContent = `GAP = compared operator weighted score minus ${baseline} weighted score. Positive values mean the compared operator leads.`;
    pane.append(gapNote);

    const rows = Array.isArray(selected.rows) ? selected.rows : [];
    appendPriorityGapScale(pane, selected, rows);
    const comparisons = comparison === 'all'
      ? operators
      : operators.filter(operator => `operator:${operator}` === comparison);
    if (!comparisons.length || !rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = comparisons.length ? 'No KPI rows are available for this comparison context.' : 'No operators can be compared with the selected reference operator.';
      pane.append(empty);
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-priority-table scoring-gap-summary-table';
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const [title, key] of [['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type']]) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = title;
      th.dataset.column = key;
      header.append(th);
    }
    for (const operator of comparisons) {
      const presentation = operatorPresentation(selected, operator);
      const th = document.createElement('th');
      th.scope = 'col';
      th.className = 'scoring-gap-header scoring-gap-operator-header';
      th.dataset.column = 'gap';
      th.textContent = `${presentation.label} − ${baseline}`;
      th.title = `${operator} weighted score minus reference ${baselineRaw} weighted score`;
      if (presentation.color) th.style.setProperty('--operator-accent', presentation.color);
      header.append(th);
    }
    thead.append(header);

    const tbody = document.createElement('tbody');
    for (let index = 0; index < rows.length; index += 1) {
      const item = rows[index];
      const row = document.createElement('tr');
      const category = String(item?.category ?? '');
      if (index === 0 || String(rows[index - 1]?.category ?? '') !== category) {
        let span = 1;
        while (index + span < rows.length && String(rows[index + span]?.category ?? '') === category) span += 1;
        const categoryCell = document.createElement('td');
        categoryCell.dataset.column = 'category';
        categoryCell.rowSpan = span;
        categoryCell.textContent = category || 'Unclassified';
        row.append(categoryCell);
      }
      const kpiCell = document.createElement('td');
      kpiCell.dataset.column = 'kpi';
      kpiCell.textContent = String(item?.kpi || item?.kpi_code || 'N/A');
      kpiCell.title = String(item?.kpi_code || item?.kpi || '');
      row.append(kpiCell);
      const typeCell = document.createElement('td');
      typeCell.dataset.column = 'type';
      const kpiType = String(item?.kpi_type ?? '');
      typeCell.textContent = !kpiType || kpiType.toLowerCase() === 'unknown' ? 'Not classified' : kpiType;
      if (kpiType.toLowerCase() === 'reliable') typeCell.dataset.kpiType = 'reliable';
      row.append(typeCell);

      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      for (const operator of comparisons) addMatrixGapCell(row, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''));
      tbody.append(row);
    }
    table.append(thead, tbody);

    const total = selected.total && typeof selected.total === 'object' ? selected.total : {};
    const totalGaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
    const totalGapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
    if (Object.keys(totalGaps).length) {
      const tfoot = document.createElement('tfoot');
      const totalRow = document.createElement('tr');
      const labelCell = document.createElement('th');
      labelCell.scope = 'row';
      labelCell.colSpan = 3;
      labelCell.textContent = 'Total signed GAP';
      totalRow.append(labelCell);
      for (const operator of comparisons) addMatrixGapCell(totalRow, firstValue(totalGaps, [operator], null), firstValue(totalGapColors, [operator], ''));
      tfoot.append(totalRow);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
  }

  function findKey(row, candidates) {
    const entries = Object.keys(row || {});
    for (const candidate of candidates) {
      const found = entries.find(key => key.toLowerCase() === candidate.toLowerCase());
      if (found) return found;
    }
    return null;
  }

  function rowText(row, candidates) {
    const key = findKey(row, candidates);
    return key ? String(row[key] ?? '') : '';
  }

  function scoreNumber(row) {
    const key = findKey(row, ['weighted_points', 'weighted_score', 'score', 'total_score', 'scoring', 'points']);
    if (!key) return null;
    if (row[key] === null || row[key] === undefined || String(row[key]).trim() === '') return null;
    const value = Number(row[key]);
    return Number.isFinite(value) ? {key, value} : null;
  }

  function aggregationValue(row, level) {
    const aliases = {
      'Dataset Type': ['dataset_type', 'cdr_type', 'dataset_kind', 'kind'],
      'Vendor': ['vendor', 'ran_vendor', 'manufacturer'],
      'Region': ['region', 'region_name'],
      'City': ['city', 'city_name'],
      'Operator': ['operator', 'operator_name', 'mno'],
    };
    const candidates = [level, ...(aliases[level] || [])];
    const key = findKey(row, candidates);
    return key ? String(row[key] ?? '') : '';
  }

  function makeSvgChart(title, rows, operatorTable) {
    const categories = [...new Set(rows.map(row => row.category))];
    const presentSeries = new Set(rows.map(row => row.series));
    const mappedOrder = Array.isArray(operatorTable?.operators) ? operatorTable.operators.map(String) : [];
    const series = [...mappedOrder.filter(name => presentSeries.has(name)),
      ...[...presentSeries].filter(name => !mappedOrder.includes(name)).sort((left, right) => left.localeCompare(right))];
    const width = Math.max(1180, categories.length * Math.max(168, series.length * 38 + 22) + 150);
    const height = 700;
    const left = 86, right = 28, top = 76, bottom = 150;
    const chartHeight = height - top - bottom;
    const maxValue = Math.max(0, ...rows.map(row => Number(row.value)).filter(Number.isFinite));
    const scaleMaximum = maxValue > 0 ? maxValue * 1.16 : 1;
    const step = (width - left - right) / Math.max(categories.length, 1);
    const fallbackColors = ['#14867d', '#df7a45', '#5a82aa', '#8b63b1', '#b49a32'];
    const presentations = new Map(series.map((name, index) => {
      const presentation = operatorPresentation(operatorTable, name);
      return [name, {...presentation, chartColor: presentation.color || fallbackColors[index % fallbackColors.length]}];
    }));
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', title);

    series.forEach((name, index) => {
      const slot = (width - left - right) / Math.max(series.length, 1);
      const x = left + index * slot;
      const presentation = presentations.get(name);
      const swatch = document.createElementNS(svg.namespaceURI, 'rect');
      swatch.setAttribute('x', String(x)); swatch.setAttribute('y', '25'); swatch.setAttribute('width', '14'); swatch.setAttribute('height', '14');
      swatch.setAttribute('rx', '3'); swatch.setAttribute('fill', presentation.chartColor);
      const legend = document.createElementNS(svg.namespaceURI, 'text');
      legend.setAttribute('x', String(x + 21)); legend.setAttribute('y', '37');
      legend.setAttribute('class', 'scoring-chart-legend');
      legend.textContent = presentation.label;
      const fullName = document.createElementNS(svg.namespaceURI, 'title');
      fullName.textContent = name; legend.append(fullName);
      svg.append(swatch, legend);
    });

    const baselineY = top + chartHeight;
    for (let tickIndex = 0; tickIndex <= 4; tickIndex += 1) {
      const value = scaleMaximum * (4 - tickIndex) / 4;
      const y = top + chartHeight * tickIndex / 4;
      const grid = document.createElementNS(svg.namespaceURI, 'line');
      grid.setAttribute('x1', String(left)); grid.setAttribute('x2', String(width - right));
      grid.setAttribute('y1', String(y)); grid.setAttribute('y2', String(y));
      grid.setAttribute('stroke', tickIndex === 4 ? '#aeb9bd' : '#e1e7e8');
      if (tickIndex !== 4) grid.setAttribute('stroke-dasharray', '4 5');
      const tick = document.createElementNS(svg.namespaceURI, 'text');
      tick.setAttribute('x', String(left - 12)); tick.setAttribute('y', String(y + 4));
      tick.setAttribute('text-anchor', 'end'); tick.setAttribute('class', 'scoring-chart-tick');
      tick.textContent = value.toLocaleString(undefined, {maximumFractionDigits: 2});
      svg.append(grid, tick);
    }
    const axisLabel = document.createElementNS(svg.namespaceURI, 'text');
    axisLabel.setAttribute('x', '22'); axisLabel.setAttribute('y', String(top + chartHeight / 2));
    axisLabel.setAttribute('text-anchor', 'middle'); axisLabel.setAttribute('class', 'scoring-chart-axis-label');
    axisLabel.setAttribute('transform', `rotate(-90 22 ${top + chartHeight / 2})`);
    axisLabel.textContent = 'Weighted score (points)';
    svg.append(axisLabel);

    categories.forEach((category, categoryIndex) => {
      const groupWidth = step * .86;
      const slotWidth = groupWidth / Math.max(series.length, 1);
      const barWidth = Math.min(48, slotWidth * .64);
      const groupStart = left + step * categoryIndex + (step - groupWidth) / 2;
      series.forEach((seriesName, seriesIndex) => {
        const row = rows.find(candidate => candidate.category === category && candidate.series === seriesName);
        if (!row) return;
        const x = groupStart + slotWidth * seriesIndex + (slotWidth - barWidth) / 2;
        if (row.value === null || row.value === undefined || !Number.isFinite(Number(row.value))) {
          const unavailable = svgElement(svg, 'text', {x: x + barWidth / 2, y: baselineY - 7, 'text-anchor': 'middle', class: 'scoring-chart-unavailable'});
          unavailable.textContent = 'N/A';
          unavailable.append(svgElement(svg, 'title'));
          unavailable.lastChild.textContent = 'KPI or environment coverage is unavailable for this operator.';
          svg.append(unavailable);
          return;
        }
        const barHeight = Math.max(0, row.value / scaleMaximum * chartHeight);
        const barTop = baselineY - barHeight;
        const color = presentations.get(seriesName).chartColor;
        const rect = document.createElementNS(svg.namespaceURI, 'rect');
        rect.setAttribute('x', String(x)); rect.setAttribute('y', String(barTop));
        rect.setAttribute('width', String(barWidth)); rect.setAttribute('height', String(Math.max(0, barHeight)));
        rect.setAttribute('rx', '4'); rect.setAttribute('fill', color);
        rect.setAttribute('aria-label', `${category}, ${presentations.get(seriesName).label}: ${row.value}`);
        const barTitle = document.createElementNS(svg.namespaceURI, 'title');
        barTitle.textContent = `${category} · ${presentations.get(seriesName).label}: ${row.value.toLocaleString(undefined, {maximumFractionDigits: 3})}${row.complete === false ? ' (partial coverage)' : ''}`;
        rect.append(barTitle);
        const value = document.createElementNS(svg.namespaceURI, 'text');
        value.setAttribute('x', String(x + barWidth / 2));
        value.setAttribute('y', String(Math.max(top + 14, barTop - 7 - (seriesIndex % 2) * 22)));
        value.setAttribute('text-anchor', 'middle'); value.setAttribute('class', 'scoring-chart-value');
        value.textContent = `${Number.isInteger(row.value) ? row.value.toLocaleString() : row.value.toLocaleString(undefined, {maximumFractionDigits: 2})}${row.complete === false ? '*' : ''}`;
        svg.append(rect, value);
      });
      const lines = [];
      let currentLine = '';
      for (const word of String(category).split(/\s+/)) {
        const candidate = currentLine ? `${currentLine} ${word}` : word;
        if (candidate.length > 22 && currentLine) {
          lines.push(currentLine);
          currentLine = word;
        } else currentLine = candidate;
      }
      if (currentLine) lines.push(currentLine);
      if (lines.length > 2) lines.splice(1, lines.length - 2, `${lines.slice(1).join(' ').slice(0, 22)}…`);
      const label = document.createElementNS(svg.namespaceURI, 'text');
      const labelX = left + step * categoryIndex + step / 2;
      label.setAttribute('x', String(labelX)); label.setAttribute('y', String(baselineY + 24));
      label.setAttribute('text-anchor', 'middle'); label.setAttribute('class', 'scoring-chart-category');
      lines.forEach((line, lineIndex) => {
        const span = document.createElementNS(svg.namespaceURI, 'tspan');
        span.setAttribute('x', String(labelX)); span.setAttribute('dy', lineIndex ? '1.15em' : '0');
        span.textContent = line;
        label.append(span);
      });
      const fullCategory = document.createElementNS(svg.namespaceURI, 'title');
      fullCategory.textContent = category; label.append(fullCategory);
      svg.append(label);
    });
    return svg;
  }

  function chartTableForRow(row, scoreTables) {
    return scoreTables.find(table => comparisonScopeFields.every(field => String(firstValue(table.context || {}, [field], '') ?? '')
      === String(firstValue(row, [field], '') ?? '')));
  }

  function scoreChartRows(scoreTables) {
    const chartRows = [];
    for (const table of scoreTables) {
      const operators = Array.isArray(table?.operators) ? table.operators.map(String) : [];
      const grouped = new Map();
      for (const item of Array.isArray(table?.rows) ? table.rows : []) {
        const category = String(item?.category || 'Other');
        if (!grouped.has(category)) grouped.set(category, new Map());
        const byOperator = grouped.get(category);
        for (const operator of operators) {
          if (!byOperator.has(operator)) byOperator.set(operator, {points: 0, hasPoints: false, complete: true, count: 0});
          const aggregate = byOperator.get(operator);
          aggregate.count += 1;
          const cell = operatorValue(item?.values || {}, operator);
          const rawPoints = cell && typeof cell === 'object' ? firstValue(cell, ['points', 'weighted_points'], null) : null;
          const points = rawPoints === null || rawPoints === undefined || String(rawPoints).trim() === '' ? Number.NaN : Number(rawPoints);
          if (Number.isFinite(points)) {
            aggregate.points += points;
            aggregate.hasPoints = true;
          }
          if (!cell || cell.complete !== true || !Number.isFinite(points)) aggregate.complete = false;
        }
      }
      for (const [category, byOperator] of grouped) {
        for (const operator of operators) {
          const aggregate = byOperator.get(operator);
          const value = aggregate?.hasPoints ? aggregate.points : null;
          chartRows.push({
            ...(table.context || {}),
            category,
            operator,
            weighted_points: value,
            complete: Boolean(aggregate?.count && aggregate.complete),
          });
        }
      }
    }
    return chartRows;
  }

  function makeExpandableChartCard(title, meta, chart) {
    const card = document.createElement('article');
    card.className = 'scoring-chart-card';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    const heading = document.createElement('h4');
    heading.textContent = title;
    heading.title = title;
    card.setAttribute('aria-label', `${title}. Double-click or press Enter to enlarge.`);
    card.dataset.chartMeta = meta || '';
    const scroll = document.createElement('div');
    scroll.className = 'scoring-chart-scroll';
    scroll.append(chart);
    card.append(heading, scroll);
    card.addEventListener('dblclick', () => openExpandedChart(card));
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openExpandedChart(card);
      }
    });
    return card;
  }

  function renderCharts(pane, source, scoreTables) {
    pane.replaceChildren();
    const rows = scoreTables.length
      ? scoreChartRows(scoreTables).map(row => ({row, score: {value: row.weighted_points}}))
      : normalizeRows(source).map(row => ({row, score: scoreNumber(row)})).filter(entry => entry.score);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No chart rows are available for this scoring job.';
      pane.append(empty);
      return;
    }
    const dimensionFields = ['campaign', 'region', 'city', 'vendor', 'dataset_type', 'environment'];
    const groups = new Map();
    for (const entry of rows) {
      const row = entry.row;
      const dimensions = dimensionFields.map(field => [field, rowText(row, [field])]).filter(([, value]) => value);
      const groupKey = JSON.stringify(dimensions);
      const rowContext = Object.fromEntries(dimensions);
      const operatorTable = chartTableForRow(row, scoreTables);
      const title = operatorTable?.title || (dimensions.length ? dimensions.map(([field, value]) => `${humanizeKey(field)}: ${value}`).join(' · ') : 'Overall scope');
      const category = rowText(row, ['category']) || 'Overall';
      const series = rowText(row, ['operator', 'operator_name', 'mno']) || 'Score';
      if (!groups.has(groupKey)) groups.set(groupKey, {title, context: operatorTable?.context || rowContext, rows: [], operatorTable});
      groups.get(groupKey).rows.push({category, series, value: entry.score.value, complete: row.complete !== false});
    }
    const selected = appendComparisonSelector(pane, [...groups.values()], 'score', 'chart');
    appendContextHeader(pane, selected, 'score', 'Scoring Chart');
    const chart = makeSvgChart('Weighted score points by KPI category', selected.rows, selected.operatorTable);
    chart.style.minWidth = `${chart.viewBox.baseVal.width}px`;
    pane.append(makeExpandableChartCard('Weighted score points by KPI category', contextLabel(selected.context), chart));
    pane.classList.add('scoring-chart-grid');
  }

  function bestNetworkKind(item) {
    const sourceKind = String(firstValue(item, ['source_kind', 'sourceKind'], '')).toLowerCase();
    if (sourceKind === 'voice' || sourceKind === 'speech') return 'Voice';
    if (sourceKind === 'data') return 'Data';
    const category = String(item?.category || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, ' ');
    return ['CLASSIC CALLS', 'WHATSAPP CALLS', 'MULTI RAB'].includes(category) ? 'Voice' : 'Data';
  }

  function bestNetworkTotals(tableData) {
    const operators = Array.isArray(tableData?.operators) ? tableData.operators.map(String) : [];
    const rows = Array.isArray(tableData?.rows) ? tableData.rows : [];
    const kinds = ['Voice', 'Data'];
    const allocation = {Voice: 0, Data: 0};
    const totals = Object.fromEntries(operators.map(operator => [operator, Object.fromEntries(kinds.map(kind => [kind, {points: 0, hasPoints: false, complete: true, rows: 0}]))]));
    for (const item of rows) {
      const kind = bestNetworkKind(item);
      const maxPoints = Number(item?.max_points);
      if (Number.isFinite(maxPoints)) allocation[kind] += maxPoints;
      for (const operator of operators) {
        const target = totals[operator][kind];
        target.rows += 1;
        const cell = operatorValue(item?.values || {}, operator);
        const rawPoints = cell && typeof cell === 'object' ? firstValue(cell, ['points', 'weighted_points'], null) : null;
        const points = rawPoints === null || rawPoints === undefined || String(rawPoints).trim() === '' ? Number.NaN : Number(rawPoints);
        if (Number.isFinite(points)) {
          target.points += points;
          target.hasPoints = true;
        }
        if (!cell || cell.complete !== true || !Number.isFinite(points)) target.complete = false;
      }
    }
    for (const operator of operators) {
      for (const kind of kinds) {
        const target = totals[operator][kind];
        target.value = target.hasPoints ? target.points : null;
        target.complete = target.rows > 0 && target.complete;
      }
    }
    return {operators, rows, allocation, totals};
  }

  function svgElement(svg, name, attributes = {}) {
    const node = document.createElementNS(svg.namespaceURI, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  }

  function lightenHexColor(color, amount = .58) {
    const safe = safeHexColor(color);
    if (!safe) return '#a9cfca';
    const channels = [1, 3, 5].map(offset => Number.parseInt(safe.slice(offset, offset + 2), 16));
    return `#${channels.map(channel => Math.round(channel + (255 - channel) * amount).toString(16).padStart(2, '0')).join('')}`;
  }

  function makeBestNetworkBars(tableData, data) {
    const width = Math.max(980, data.operators.length * 190 + 170);
    const height = 500;
    const left = 92, right = 36, top = 72, bottom = 124;
    const plotHeight = height - top - bottom;
    const maxAllocation = data.allocation.Voice + data.allocation.Data;
    const maxActual = Math.max(0, ...data.operators.map(operator => ['Voice', 'Data'].reduce((sum, kind) => sum + (data.totals[operator][kind].value ?? 0), 0)));
    const maxValue = Math.max(maxAllocation, maxActual);
    const scaleMaximum = maxValue > 0 ? maxValue * 1.13 : 1;
    const step = (width - left - right) / Math.max(data.operators.length, 1);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg scoring-best-network-bars');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Voice and Data weighted points by operator');
    const barColors = new Map(data.operators.map((operator, index) => {
      const mapped = operatorPresentation(tableData, operator);
      return [operator, {label: mapped.label, color: mapped.color || ['#14867d', '#df7a45', '#5a82aa', '#8b63b1'][index % 4]}];
    }));
    const baselineY = top + plotHeight;
    for (let tickIndex = 0; tickIndex <= 4; tickIndex += 1) {
      const value = scaleMaximum * (4 - tickIndex) / 4;
      const y = top + plotHeight * tickIndex / 4;
      svg.append(svgElement(svg, 'line', {x1: left, x2: width - right, y1: y, y2: y, stroke: tickIndex === 4 ? '#aeb9bd' : '#e1e7e8', ...(tickIndex === 4 ? {} : {'stroke-dasharray': '4 5'})}));
      const tick = svgElement(svg, 'text', {x: left - 12, y: y + 4, 'text-anchor': 'end', class: 'scoring-chart-tick'});
      tick.textContent = value.toLocaleString(undefined, {maximumFractionDigits: 2});
      svg.append(tick);
    }
    const axis = svgElement(svg, 'text', {x: 22, y: top + plotHeight / 2, 'text-anchor': 'middle', class: 'scoring-chart-axis-label', transform: `rotate(-90 22 ${top + plotHeight / 2})`});
    axis.textContent = 'Weighted score (points)';
    svg.append(axis);
    data.operators.forEach((operator, index) => {
      const presentation = barColors.get(operator);
      const barWidth = Math.min(92, step * .48);
      const x = left + step * index + (step - barWidth) / 2;
      let stackY = baselineY;
      let totalPoints = 0;
      let hasPoints = false;
      let complete = true;
      for (const kind of ['Data', 'Voice']) {
        const cell = data.totals[operator][kind];
        if (cell.value === null) {
          complete = false;
          continue;
        }
        hasPoints = true;
        totalPoints += cell.value;
        complete = complete && cell.complete;
        const segmentHeight = Math.max(0, cell.value / scaleMaximum * plotHeight);
        const segmentY = stackY - segmentHeight;
        const color = kind === 'Data' ? presentation.color : lightenHexColor(presentation.color);
        const rect = svgElement(svg, 'rect', {x, y: segmentY, width: barWidth, height: segmentHeight, rx: 3, fill: color});
        const tip = svgElement(svg, 'title');
        tip.textContent = `${presentation.label} · ${kind}: ${cell.value.toLocaleString(undefined, {maximumFractionDigits: 2})}${cell.complete ? '' : ' (partial coverage)'}`;
        rect.append(tip);
        svg.append(rect);
        const segmentLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: segmentY + Math.max(13, segmentHeight / 2 + 4), 'text-anchor': 'middle', class: 'scoring-best-network-segment'});
        segmentLabel.textContent = `${kind === 'Data' ? 'D' : 'V'} ${cell.value.toLocaleString(undefined, {maximumFractionDigits: 1})}${cell.complete ? '' : '*'}`;
        const labelColor = readableTextColor(color) || '#17303c';
        segmentLabel.style.fill = labelColor;
        segmentLabel.style.stroke = labelColor === '#ffffff' ? 'rgba(0,0,0,.62)' : 'rgba(255,255,255,.88)';
        svg.append(segmentLabel);
        stackY = segmentY;
      }
      const totalLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: Math.max(top + 18, stackY - 10), 'text-anchor': 'middle', class: 'scoring-chart-value'});
      totalLabel.textContent = hasPoints ? `${totalPoints.toLocaleString(undefined, {maximumFractionDigits: 1})}${complete ? '' : '*'}` : 'N/A';
      const totalTitle = svgElement(svg, 'title');
      totalTitle.textContent = hasPoints ? `Displayed points are not renormalized; ${complete ? 'complete coverage.' : 'coverage is incomplete.'}` : 'No operator points are available.';
      totalLabel.append(totalTitle);
      svg.append(totalLabel);
      const operatorLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: baselineY + 28, 'text-anchor': 'middle', class: 'scoring-chart-category'});
      operatorLabel.textContent = presentation.label;
      const rawLabel = svgElement(svg, 'title');
      rawLabel.textContent = operator;
      operatorLabel.append(rawLabel);
      svg.append(operatorLabel);
    });
    return svg;
  }

  function makeMaximumAllocationDonut(allocation) {
    const voiceColor = '#91cfc2';
    const dataColor = '#244b64';
    const total = allocation.Voice + allocation.Data;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 360 330');
    svg.setAttribute('class', 'scoring-chart-svg scoring-allocation-donut');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Maximum score allocation between Voice and Data KPIs');
    const radius = 82;
    const circumference = 2 * Math.PI * radius;
    const voiceLength = total > 0 ? circumference * allocation.Voice / total : 0;
    const dataCircle = svgElement(svg, 'circle', {cx: 180, cy: 145, r: radius, fill: 'none', stroke: dataColor, 'stroke-width': 38});
    const dataTitle = svgElement(svg, 'title');
    dataTitle.textContent = `Data maximum allocation: ${allocation.Data.toFixed(2)} points`;
    dataCircle.append(dataTitle);
    const voiceCircle = svgElement(svg, 'circle', {cx: 180, cy: 145, r: radius, fill: 'none', stroke: voiceColor, 'stroke-width': 38, 'stroke-dasharray': `${voiceLength} ${circumference - voiceLength}`, transform: 'rotate(-90 180 145)'});
    const voiceTitle = svgElement(svg, 'title');
    voiceTitle.textContent = `Voice maximum allocation: ${allocation.Voice.toFixed(2)} points`;
    voiceCircle.append(voiceTitle);
    svg.append(dataCircle, voiceCircle);
    const center = svgElement(svg, 'text', {x: 180, y: 139, 'text-anchor': 'middle', class: 'scoring-allocation-total'});
    center.textContent = total.toLocaleString(undefined, {maximumFractionDigits: 1});
    const unit = svgElement(svg, 'text', {x: 180, y: 162, 'text-anchor': 'middle', class: 'scoring-allocation-unit'});
    unit.textContent = 'max points';
    svg.append(center, unit);
    const legendItems = [['Voice', voiceColor, allocation.Voice], ['Data', dataColor, allocation.Data]];
    legendItems.forEach(([label, color, value], index) => {
      const y = 270 + index * 25;
      svg.append(svgElement(svg, 'rect', {x: 55, y: y - 11, width: 14, height: 14, rx: 3, fill: color}));
      const textLabel = svgElement(svg, 'text', {x: 78, y, class: 'scoring-allocation-legend'});
      textLabel.textContent = `${label}: ${Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})} points`;
      svg.append(textLabel);
    });
    return svg;
  }

  function renderBestNetworkChart(pane, scoreTables) {
    pane.replaceChildren();
    if (!scoreTables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No Best Network chart is available for this environment.';
      pane.append(empty);
      return;
    }
    const selected = appendComparisonSelector(pane, scoreTables, 'score');
    appendContextHeader(pane, selected, 'score', 'Best Network Chart');
    const data = bestNetworkTotals(selected);
    if (!data.operators.length || !data.rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No operator points are available for this comparison context.';
      pane.append(empty);
      return;
    }
    const layout = document.createElement('div');
    layout.className = 'scoring-best-network-layout';
    const meta = contextLabel(selected.context);
    const bars = makeBestNetworkBars(selected, data);
    layout.append(makeExpandableChartCard('Voice and Data weighted points by operator', meta, bars));
    const donut = makeMaximumAllocationDonut(data.allocation);
    layout.append(makeExpandableChartCard('Maximum score allocation', meta, donut));
    pane.append(layout);
  }

  function openExpandedChart(card) {
    const sourceChart = card?.querySelector('.scoring-chart-svg');
    if (!sourceChart || !chartOverlay || !expandedChart) return;
    chartFocusReturn = card;
    const title = card.querySelector('h4')?.textContent || 'Scoring chart';
    expandedChartTitle.textContent = title;
    expandedChartMeta.textContent = card.dataset.chartMeta || (selectedEnvironment ? environmentLabel(selectedEnvironment) : '');
    const chart = sourceChart.cloneNode(true);
    chart.style.minWidth = '0';
    expandedChart.replaceChildren(chart);
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    chartOverlay.hidden = false;
    expandedChartClose?.focus();
  }

  function closeExpandedChart() {
    if (!chartOverlay || chartOverlay.hidden) return;
    chartOverlay.hidden = true;
    expandedChart.replaceChildren();
    document.body.style.overflow = previousBodyOverflow;
    if (chartFocusReturn?.isConnected) chartFocusReturn.focus();
    chartFocusReturn = null;
  }

  function renderWarnings(warnings) {
    const box = root.querySelector('[data-warning-box]');
    const list = root.querySelector('[data-warning-list]');
    const items = Array.isArray(warnings) ? warnings : (warnings ? [warnings] : []);
    list.replaceChildren();
    box.hidden = !items.length;
    for (const warning of items) {
      const item = document.createElement('li');
      item.textContent = typeof warning === 'string' ? warning : displayValue(warning);
      list.append(item);
    }
  }

  const environmentOrder = ['DriveCity', 'DriveConnectionroad', 'Combined'];
  const comparisonScopeFields = ['campaign', 'region', 'city', 'vendor', 'dataset_type'];

  function environmentOf(table) {
    return String(table?.context?.environment ?? table?.environment ?? '');
  }

  function scopeIdentity(context) {
    return JSON.stringify(comparisonScopeFields.map(field => [field, String(firstValue(context, [field], '') ?? '')]));
  }

  function availableScoreEnvironments(tables) {
    const actualByScope = new Map();
    const available = new Set();
    for (const table of tables) {
      const environment = environmentOf(table);
      if (!environment || environment === 'Combined') continue;
      available.add(environment);
      const scope = scopeIdentity(table.context || {});
      if (!actualByScope.has(scope)) actualByScope.set(scope, new Set());
      actualByScope.get(scope).add(environment);
    }
    const combinedIsAvailable = tables.some(table => environmentOf(table) === 'Combined'
      && ['DriveCity', 'DriveConnectionroad'].every(environment => actualByScope.get(scopeIdentity(table.context || {}))?.has(environment)));
    const ordered = [...available].sort((left, right) => {
      const leftIndex = environmentOrder.indexOf(left);
      const rightIndex = environmentOrder.indexOf(right);
      return (leftIndex < 0 ? environmentOrder.length : leftIndex) - (rightIndex < 0 ? environmentOrder.length : rightIndex) || left.localeCompare(right);
    });
    if (combinedIsAvailable) ordered.push('Combined');
    return ordered;
  }

  function environmentLabel(environment) {
    if (environment === 'DriveCity') return 'Drive City';
    if (environment === 'DriveConnectionroad') return 'Drive Connection Road';
    return environment;
  }

  function syncResultEnvironment(tables) {
    const environments = availableScoreEnvironments(tables);
    if (!environments.length) {
      selectedEnvironment = null;
      environmentSelect.replaceChildren();
      environmentControl.hidden = true;
      return environments;
    }
    if (!environments.includes(selectedEnvironment)) {
      selectedEnvironment = environments.includes('Combined')
        ? 'Combined'
        : (environments.includes('DriveCity') ? 'DriveCity' : environments[0]);
    }
    const currentOptions = [...environmentSelect.options].map(option => option.value);
    if (JSON.stringify(currentOptions) !== JSON.stringify(environments)) {
      environmentSelect.replaceChildren();
      for (const environment of environments) {
        const option = document.createElement('option');
        option.value = environment;
        option.textContent = environmentLabel(environment);
        environmentSelect.append(option);
      }
    }
    environmentSelect.value = selectedEnvironment;
    environmentControl.hidden = false;
    return environments;
  }

  function chartRowsForEnvironment(source, scoreTables) {
    const rows = normalizeRows(source);
    if (!scoreTables.length) return rows;
    return rows.filter(row => {
      if (String(firstValue(row, ['environment'], '')) !== selectedEnvironment) return false;
      return scoreTables.some(table => environmentOf(table) === selectedEnvironment
        && comparisonScopeFields.every(field => String(firstValue(table.context || {}, [field], '') ?? '')
          === String(firstValue(row, [field], '') ?? '')));
    });
  }

  function renderResult(payload, job) {
    currentResults = payload;
    const scoringRows = payload.scoring ?? payload.scoring_rows ?? [];
    const gapRows = payload.gap ?? payload.gap_rows ?? [];
    const scoringPane = root.querySelector('[data-result-pane="scoring"]');
    const chartPane = root.querySelector('[data-result-pane="charts"]');
    const gapPane = root.querySelector('[data-result-pane="gap"]');
    const bestNetworkPane = root.querySelector('[data-result-pane="best-network"]');
    const views = payload.views && typeof payload.views === 'object' ? payload.views : {};
    const allScoreTables = normalizeRows(views.score_tables ?? payload.score_tables ?? payload.scoring_views?.score_tables ?? []);
    const allGapTables = normalizeRows(views.gap_tables ?? payload.gap_tables ?? payload.scoring_views?.gap_tables ?? []);
    const allGapSummaryTables = normalizeRows(views.gap_summary_tables ?? payload.gap_summary_tables ?? payload.scoring_views?.gap_summary_tables ?? []);
    syncResultEnvironment(allScoreTables);
    const scoreTables = allScoreTables.filter(table => environmentOf(table) === selectedEnvironment);
    const gapTables = allGapTables.filter(table => environmentOf(table) === selectedEnvironment);
    const gapSummaryTables = allGapSummaryTables.filter(table => environmentOf(table) === selectedEnvironment);
    const thresholdLegend = normalizeRows(views.threshold_legend ?? payload.threshold_legend ?? []);
    const totalsRows = normalizeRows(payload.totals ?? payload.scoring_totals ?? []);
    const detailRows = normalizeRows(scoringRows);
    const hasScoringViews = Array.isArray(views.score_tables) || Array.isArray(payload.score_tables) || Array.isArray(payload.scoring_views?.score_tables);
    const hasGapViews = Array.isArray(views.gap_tables) || Array.isArray(payload.gap_tables) || Array.isArray(payload.scoring_views?.gap_tables)
      || Array.isArray(views.gap_summary_tables) || Array.isArray(payload.gap_summary_tables) || Array.isArray(payload.scoring_views?.gap_summary_tables);
    if (hasScoringViews) {
      renderScoringViews(scoringPane, scoreTables, thresholdLegend);
    } else if (totalsRows.length) {
      scoringPane.replaceChildren();
      const summaryHeading = document.createElement('h4');
      summaryHeading.className = 'scoring-table-section-title';
      summaryHeading.textContent = 'Scoring Summary';
      const summaryTable = document.createElement('div');
      summaryTable.className = 'scoring-table-section';
      renderTable(summaryTable, totalsRows, 'No scoring summary rows are available.');
      scoringPane.append(summaryHeading, summaryTable);
      const detailHeading = document.createElement('h4');
      detailHeading.className = 'scoring-table-section-title';
      detailHeading.textContent = 'KPI Scoring Details';
      const detailTable = document.createElement('div');
      detailTable.className = 'scoring-table-section';
      renderTable(detailTable, detailRows, 'No KPI detail rows are available.');
      scoringPane.append(detailHeading, detailTable);
    } else {
      scoringPane.replaceChildren();
      renderTable(scoringPane, detailRows, 'This job has no scoring table rows.');
    }
    chartPane.classList.remove('scoring-chart-grid');
    renderCharts(chartPane, chartRowsForEnvironment(payload.charts ?? [], allScoreTables), scoreTables);
    renderBestNetworkChart(bestNetworkPane, scoreTables);
    const gapTotals = normalizeRows(payload.gap_totals ?? []);
    if (gapSummaryTables.length) {
      renderGapSummaryViews(gapPane, gapSummaryTables);
    } else if (hasGapViews) {
      renderGapViews(gapPane, gapTables);
    } else if (gapTotals.length) {
      gapPane.replaceChildren();
      for (const [title, rows] of [['GAP Summary', gapTotals], ['KPI GAP Details', normalizeRows(gapRows)]]) {
        const heading = document.createElement('h4');
        heading.className = 'scoring-table-section-title';
        heading.textContent = title;
        const section = document.createElement('div');
        section.className = 'scoring-table-section';
        renderTable(section, rows, 'No comparable GAP rows are available.');
        gapPane.append(heading, section);
      }
    } else {
      renderTable(gapPane, gapRows, 'No GAP rows are available for the selected baseline operator.');
    }
    const warnings = payload.warnings ?? job?.warnings ?? [];
    renderWarnings(warnings);
    const levels = jobLevels(job || payload.job || {}) || 'Operator';
    const mode = valueOf(job || payload.job, ['nr_mode'], 'All NR Modes');
    const baseline = valueOf(job || payload.job, ['baseline_operator'], 'EE');
    const environmentMeta = selectedEnvironment ? ` · ${environmentLabel(selectedEnvironment)}` : '';
    resultMeta.textContent = `${formatDate(valueOf(job || payload.job, ['created_at', 'completed_at', 'submitted_at'], ''))} · ${levels} · ${mode}${environmentMeta} · GAP: compared operator minus ${baseline} · Filters: ${contextFilterSummary(job || payload.job)}`;
    setExportLinks(jobIdOf(job || payload.job || {}), true);
  }

  function renderNoResult(text) {
    for (const pane of resultPanes) {
      pane.replaceChildren();
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = text;
      pane.append(empty);
    }
    root.querySelector('[data-warning-box]').hidden = true;
    setExportLinks('', false);
  }

  async function loadJob(job, force = false) {
    const id = jobIdOf(job);
    if (!id) return;
    selectedJobId = id;
    selectedJob = job;
    renderJobs();
    if (!force && resultCache.has(id) && isComplete(job)) {
      currentResults = resultCache.get(id);
      renderResult(currentResults, job);
      return;
    }
    try {
      const payload = await requestJson(`${jobsUrl}/${encodeURIComponent(id)}`);
      if (deletedJobIds.has(id) || selectedJobId !== id) return;
      const record = payload.job || payload;
      selectedJob = record;
      const status = normalizeStatus(record);
      if (isComplete(record) || payload.scoring || payload.gap) {
        currentResults = payload;
        resultCache.set(id, payload);
        renderResult(payload, record);
      } else if (status === 'failed') {
        const error = valueOf(record, ['error', 'error_message', 'last_error'], 'This scoring job failed without an error message.');
        renderNoResult(error);
        resultMeta.textContent = `${jobSummary(record)} · Failed · ${error} · Filters: ${contextFilterSummary(record)}`;
      } else {
        renderNoResult('Scoring results will appear here when the job completes.');
        resultMeta.textContent = `${jobSummary(record)} · ${status} · ${jobLevels(record)} · Filters: ${contextFilterSummary(record)}`;
        setExportLinks('', false);
      }
    } catch (error) {
      if (deletedJobIds.has(id) || selectedJobId !== id) return;
      renderNoResult(error.message || 'The selected job could not be loaded.');
      resultMeta.textContent = 'Unable to load this scoring job.';
      setMessage(error.message || 'The selected job could not be loaded.', 'error');
    }
  }

  async function refreshJobs() {
    if (refreshInFlight) return;
    refreshInFlight = true;
    try {
      const payload = await requestJson(jobsUrl);
      jobs = (Array.isArray(payload) ? payload : (Array.isArray(payload.jobs) ? payload.jobs : []))
        .filter(job => !deletedJobIds.has(jobIdOf(job)));
      const ordered = sortedJobs(jobs);
      const retained = userSelectedJob && selectedJobId ? ordered.find(job => jobIdOf(job) === selectedJobId) : null;
      if (retained) {
        selectedJob = retained;
      } else {
        const requested = requestedJobId ? ordered.find(job => jobIdOf(job) === requestedJobId) : null;
        selectedJob = requested && isActive(requested) ? requested : (ordered.find(isComplete) || ordered[0] || null);
        selectedJobId = selectedJob ? jobIdOf(selectedJob) : null;
      }
      renderJobs();
      if (selectedJob) {
        const hasCached = resultCache.has(jobIdOf(selectedJob)) && isComplete(selectedJob);
        if (!hasCached || isActive(selectedJob)) await loadJob(selectedJob, isActive(selectedJob));
        else renderResult(resultCache.get(jobIdOf(selectedJob)), selectedJob);
      } else {
        currentResults = null;
        resultMeta.textContent = 'No saved scoring result selected.';
        renderNoResult('Run a scoring job or select a saved job to see its results.');
      }
      const anyActive = jobs.some(isActive);
      if (anyActive && !timer) timer = window.setInterval(refreshJobs, 3500);
      if (!anyActive && timer) { window.clearInterval(timer); timer = null; }
    } catch (error) {
      jobList.innerHTML = '';
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = error.message || 'Scoring jobs could not be loaded.';
      jobList.append(empty);
      setMessage(error.message || 'Scoring jobs could not be loaded.', 'error');
    } finally {
      refreshInFlight = false;
    }
  }

  async function deleteJob(id) {
    const job = jobs.find(record => jobIdOf(record) === id);
    if (!job || deletingJobIds.has(id)) return;
    const copy = `Delete scoring job ${id} and its saved results?${isActive(job) ? ' Its pending result will be discarded.' : ''}`;
    const accepted = typeof showConfirmDialog === 'function'
      ? await showConfirmDialog(copy, {title: 'Delete scoring job', confirmLabel: 'Delete'})
      : window.confirm(copy);
    if (!accepted) return;
    deletingJobIds.add(id);
    renderJobs();
    try {
      await requestJson(`${jobsUrl}/${encodeURIComponent(id)}`, {method: 'DELETE'});
      deletedJobIds.add(id);
      resultCache.delete(id);
      jobs = jobs.filter(record => jobIdOf(record) !== id);
      if (selectedJobId === id) {
        selectedJobId = null;
        selectedJob = null;
        currentResults = null;
        userSelectedJob = false;
        resultMeta.textContent = 'No saved scoring result selected.';
        renderNoResult('Run a scoring job or select a saved job to see its results.');
      }
      renderJobs();
      setMessage('Scoring job and saved results deleted.', 'success');
      await refreshJobs();
    } catch (error) {
      setMessage(error.message || 'The scoring job could not be deleted.', 'error');
    } finally {
      deletingJobIds.delete(id);
      renderJobs();
    }
  }

  async function createJob(force) {
    const datasetIds = selectedDatasetIds();
    if (!datasetIds.length) {
      setMessage('Select one or more CDR datasets first.', 'error');
      return;
    }
    const missingKinds = datasetKindOrder.filter(kind => !datasetInputs.some(input => input.checked
      && !input.closest('[data-dataset-option]')?.hidden
      && String(input.closest('[data-dataset-option]')?.dataset.datasetKind || '').toLowerCase() === kind));
    if (missingKinds.length) {
      const labels = missingKinds.map(kind => datasetKindLabels[kind]);
      setMessage(`Select at least one dataset from each CDR type: ${labels.join(', ')}.`, 'error');
      return;
    }
    const baseline = baselineInput.value.trim();
    if (!baseline) {
      setMessage('Enter a baseline operator for the GAP analysis.', 'error');
      baselineInput.focus();
      return;
    }
    const levels = [...new Set(['Operator', ...selectedLevels()])];
    const payload = {
      dataset_ids: datasetIds,
      aggregation_levels: levels,
      nr_mode: nrFilter.value || 'NSA',
      baseline_operator: baseline,
      context_filters: selectedContextFilters(),
      force,
    };
    calculateButton.disabled = true;
    recalculateButton.disabled = true;
    setMessage(force ? 'Submitting a fresh scoring calculation…' : 'Submitting scoring calculation…');
    try {
      const body = await requestJson(jobsUrl, {method: 'POST', body: JSON.stringify(payload)});
      const job = body.job || body;
      const id = jobIdOf(job);
      if (!id) throw new Error('The scoring service did not return a job identifier.');
      selectedJobId = id;
      selectedJob = job;
      userSelectedJob = true;
      const cached = Boolean(body.cached);
      if (cached && (body.scoring || body.gap)) {
        const result = {job, scoring: body.scoring || [], gap: body.gap || [], warnings: body.warnings || []};
        resultCache.set(id, result);
      }
      setMessage(cached ? 'Loaded the previously calculated result.' : 'Scoring job added to the background queue.', 'success');
      await refreshJobs();
      if (isActive(selectedJob)) {
        renderJobs();
        if (!timer) timer = window.setInterval(refreshJobs, 3500);
      }
    } catch (error) {
      setMessage(error.message || 'The scoring job could not be started.', 'error');
    } finally {
      updateSelection();
    }
  }

  datasetInputs.forEach(input => input.addEventListener('change', updateSelection));
  nrFilter.addEventListener('change', () => applyNrFilter(true));
  root.addEventListener('change', event => {
    if (event.target === environmentSelect && currentResults) {
      selectedEnvironment = environmentSelect.value;
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target === showKpiValuesToggle && currentResults) {
      renderResult(currentResults, selectedJob);
      return;
    }
    const gapSummaryOperator = event.target.closest('[data-gap-summary-operator]');
    if (gapSummaryOperator && currentResults) {
      contextSelections.set(gapSummaryOperator.dataset.gapSummaryStateKey, gapSummaryOperator.value);
      renderResult(currentResults, selectedJob);
      return;
    }
    const select = event.target.closest('[data-comparison-context]');
    if (!select || !currentResults) return;
    const kind = select.dataset.contextKind;
    if (select.dataset.contextSource === 'chart') {
      const identity = select.selectedOptions[0]?.dataset.contextIdentity;
      if (identity) contextSelections.set(kind, identity);
      renderResult(currentResults, selectedJob);
      return;
    }
    const views = currentResults.views && typeof currentResults.views === 'object' ? currentResults.views : {};
    const allTables = kind === 'gap'
      ? (views.gap_tables ?? currentResults.gap_tables ?? currentResults.scoring_views?.gap_tables ?? [])
      : kind === 'gap-summary'
        ? (views.gap_summary_tables ?? currentResults.gap_summary_tables ?? currentResults.scoring_views?.gap_summary_tables ?? [])
      : (views.score_tables ?? currentResults.score_tables ?? currentResults.scoring_views?.score_tables ?? []);
    const tables = (Array.isArray(allTables) ? allTables : []).filter(table => environmentOf(table) === selectedEnvironment);
    const selected = Array.isArray(tables) ? tables[Number(select.value)] : null;
    if (!selected) return;
    contextSelections.set(kind, comparisonIdentity(selected, kind));
    renderResult(currentResults, selectedJob);
  });
  calculateButton.addEventListener('click', () => createJob(false));
  recalculateButton.addEventListener('click', () => createJob(true));
  jobList.addEventListener('click', event => {
    const remove = event.target.closest('[data-delete-job-id]');
    if (remove) {
      deleteJob(remove.dataset.deleteJobId);
      return;
    }
    const button = event.target.closest('[data-job-id]');
    if (!button) return;
    const job = jobs.find(record => jobIdOf(record) === button.dataset.jobId);
    if (!job) return;
    userSelectedJob = true;
    selectedJobId = jobIdOf(job);
    selectedJob = job;
    loadJob(job, true);
  });
  root.addEventListener('click', event => {
    const tab = event.target.closest('[data-result-tab]');
    if (!tab || !root.contains(tab)) return;
    const name = tab.dataset.resultTab;
    for (const other of root.querySelectorAll('[data-result-tab]')) {
      const selected = other === tab;
      other.setAttribute('aria-selected', String(selected));
      other.tabIndex = selected ? 0 : -1;
    }
    for (const pane of root.querySelectorAll('[data-result-pane]')) pane.hidden = pane.dataset.resultPane !== name;
  });
  expandedChartClose?.addEventListener('click', closeExpandedChart);
  chartOverlay?.addEventListener('click', event => {
    if (event.target === chartOverlay) closeExpandedChart();
  });
  document.addEventListener('keydown', event => {
    if (!chartOverlay || chartOverlay.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeExpandedChart();
      return;
    }
    if (event.key !== 'Tab') return;
    if (event.shiftKey && document.activeElement === expandedChartClose) {
      event.preventDefault();
      chartDialog.focus();
    } else if (!event.shiftKey && document.activeElement === chartDialog) {
      event.preventDefault();
      expandedChartClose.focus();
    } else if (!event.shiftKey && document.activeElement === expandedChartClose) {
      event.preventDefault();
      chartDialog.focus();
    }
  });
  applyNrFilter(true);
  refreshJobs();
})();
