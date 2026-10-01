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
  const scoringConfigElement = root.querySelector('[data-scoring-config]');
  const scoringProfileSelect = root.querySelector('[data-scoring-profile]');
  let scoringConfig = {};
  try {
    scoringConfig = JSON.parse(scoringConfigElement?.textContent || '{}');
  } catch {
    scoringConfig = {};
  }
  const defaultHierarchy = ['Operator', 'Vendor', 'Region', 'City', 'Campaign'];
  const catalogueKeyByLevel = new Map([
    ['Operator', 'operators'], ['Vendor', 'vendors'], ['Region', 'regions'],
    ['City', 'cities'], ['Campaign', 'campaigns'],
  ]);
  const validHierarchy = hierarchy => Array.isArray(hierarchy)
    && hierarchy.length === defaultHierarchy.length
    && new Set(hierarchy).size === defaultHierarchy.length
    && hierarchy.every(level => catalogueKeyByLevel.has(level))
    ? hierarchy.map(String) : null;
  const scoringProfiles = (Array.isArray(scoringConfig.scoring_profiles) ? scoringConfig.scoring_profiles : [])
    .filter(profile => profile && typeof profile.id === 'string' && typeof profile.name === 'string')
    .map(profile => ({...profile, aggregation_hierarchy: validHierarchy(profile.aggregation_hierarchy)}))
    .filter(profile => profile.aggregation_hierarchy);
  const scoringProfileById = new Map(scoringProfiles.map(profile => [profile.id, profile]));
  const activeProfileId = String(scoringConfig.active_profile_id || '');
  const initialProfile = scoringProfileById.get(scoringProfileSelect?.value)
    || scoringProfileById.get(activeProfileId);
  const configuredHierarchy = validHierarchy(initialProfile?.aggregation_hierarchy)
    || validHierarchy(scoringConfig.aggregation_hierarchy) || defaultHierarchy;
  let currentHierarchy = [...configuredHierarchy];
  let contextFilterDefinitions = currentHierarchy
    .map(key => ({key, catalogueKey: catalogueKeyByLevel.get(key)}));
  const contextFilterSelects = new Map(contextFilterDefinitions.map(({key}) => [
    key, root.querySelector(`[data-scoring-context-filter="${key}"]`),
  ]));
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
  const aggregationInputByLevel = new Map(aggregationInputs.map(input => [input.value, input]));
  const contextFilterGrid = root.querySelector('[data-scoring-context-filters]');
  const aggregationLevelsContainer = root.querySelector('[data-aggregation-levels]');
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
  const tableModeSelect = root.querySelector('[data-scoring-table-mode]');
  const gapLayoutSelect = root.querySelector('[data-scoring-gap-layout]');
  const resultPanes = [...root.querySelectorAll('[data-result-pane]')];
  const resultCache = new Map();
  const contextSelections = new Map();
  const deletedJobIds = new Set();
  const deletingJobIds = new Set();
  let jobs = [];
  let selectedJobId = null;
  let selectedJob = null;
  let selectedEnvironment = 'all';
  let currentEffectiveEnvironment = null;
  let currentResults = null;
  let currentResultsJobId = null;
  let activeResultTab = root.querySelector('[data-result-tab][aria-selected="true"]')?.dataset.resultTab || 'scoring';
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
  const selectedLevels = () => currentHierarchy.filter(level => aggregationInputByLevel.get(level)?.checked);
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

  function canonicalOperatorName(value) {
    const raw = String(value ?? '').trim();
    const identity = raw.toLocaleLowerCase();
    const group = operatorGroups.find(item => operatorGroupLabels(item).some(alias => alias.toLocaleLowerCase() === identity));
    return group ? String(group.canonical).trim() : raw;
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

  function applyProfileHierarchy(hierarchy) {
    const ordered = validHierarchy(hierarchy);
    if (!ordered) return false;
    const selected = new Set(aggregationInputs.filter(input => input.checked).map(input => input.value));
    currentHierarchy = ordered;
    contextFilterDefinitions = ordered.map(key => ({key, catalogueKey: catalogueKeyByLevel.get(key)}));
    for (const level of ordered) {
      const filter = contextFilterSelects.get(level);
      const filterLabel = filter?.closest('label');
      if (filterLabel && contextFilterGrid) contextFilterGrid.append(filterLabel);
      const input = aggregationInputByLevel.get(level);
      const levelLabel = input?.closest('label');
      if (levelLabel && aggregationLevelsContainer) aggregationLevelsContainer.append(levelLabel);
      if (input) input.checked = level === 'Operator' || selected.has(level);
    }
    updateSelection();
    return true;
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
      const profileName = valueOf(job, ['scoring_profile_name', 'profile_name'], '');
      if (profileName) {
        const profileMeta = document.createElement('span');
        profileMeta.className = 'scoring-job-meta';
        profileMeta.textContent = `Scoring methodology: ${profileName}`;
        button.append(profileMeta);
      }
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

  function selectedTableMode() {
    return tableModeSelect?.value === 'summary' ? 'summary' : 'expanded';
  }

  function selectedGapLayout() {
    return gapLayoutSelect?.value === 'adjacent' ? 'adjacent' : 'end';
  }

  function appendScoreGapCells(operators, nonBaseline, layout, appendScore, appendGap) {
    if (layout === 'adjacent') {
      for (const [operatorIndex, operator] of operators.entries()) {
        appendScore(operator, operatorIndex);
        if (nonBaseline.includes(operator)) appendGap(operator);
      }
      return;
    }
    for (const [operatorIndex, operator] of operators.entries()) appendScore(operator, operatorIndex);
    for (const operator of nonBaseline) appendGap(operator);
  }

  function tableForSelectedMode(tableData) {
    if (!tableData || typeof tableData !== 'object') return tableData;
    const mode = selectedTableMode();
    const rowsKey = mode === 'summary' ? 'category_rows' : 'expanded_rows';
    const totalKey = mode === 'summary' ? 'category_total' : 'expanded_total';
    if (!Array.isArray(tableData[rowsKey])) return tableData;
    const total = tableData[totalKey] && typeof tableData[totalKey] === 'object'
      ? tableData[totalKey] : tableData.total;
    return {
      ...tableData,
      rows: tableData[rowsKey],
      total,
      ...(total && Object.hasOwn(total, 'gap_points') ? {total_gap_points: total.gap_points} : {}),
    };
  }

  function setExportLinks(jobId, enabled) {
    for (const [kind, selector] of [['scoring', '[data-export-scoring]'], ['gap', '[data-export-gap]'], ['ppt', '[data-export-ppt]']]) {
      const link = root.querySelector(selector);
      link.hidden = !enabled;
      link.href = enabled
        ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}?table_mode=${encodeURIComponent(selectedTableMode())}&gap_layout=${encodeURIComponent(selectedGapLayout())}&environment=${encodeURIComponent(selectedEnvironment || 'all')}`
        : '#';
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
      .map(key => [key, key === 'environment' ? environmentLabel(String(context[key])) : context[key]]);
    for (const [key, value] of Object.entries(context)) {
      if (!preferred.includes(key) && value !== null && value !== undefined && value !== '') entries.push([key, key === 'environment' ? environmentLabel(String(value)) : value]);
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
      .map(key => [key, key === 'environment' ? environmentLabel(String(context[key])) : context[key]]);
    for (const [key, value] of Object.entries(context)) {
      if (!preferred.includes(key) && value !== null && value !== undefined && value !== '') entries.push([key, key === 'environment' ? environmentLabel(String(value)) : value]);
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
    const nonBaseline = operators.filter(operator => !isReferenceOperator(tableData, operator));
    const gapLayout = selectedGapLayout();
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
    if (operators.length && gapLayout === 'end') {
      const group = document.createElement('th');
      group.scope = 'colgroup';
      group.colSpan = operators.length;
      group.className = 'scoring-column-group scoring-score-group';
      group.textContent = 'Score';
      header.append(group);
    }
    if (gapLayout === 'adjacent') {
      for (const operator of operators) {
        const presentation = operatorPresentation(tableData, operator);
        const isCompared = nonBaseline.includes(operator);
        const group = document.createElement('th');
        group.scope = 'colgroup';
        group.colSpan = isCompared ? 2 : 1;
        group.className = `scoring-column-group ${isCompared ? 'scoring-adjacent-group' : 'scoring-score-group'}`;
        group.textContent = `${presentation.label} · ${isCompared ? 'Score / GAP' : 'Score'}`;
        header.append(group);
      }
    } else if (nonBaseline.length) {
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
    const appendScoreHeader = (operator, index) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.dataset.column = 'score';
      const presentation = operatorPresentation(tableData, operator);
      th.textContent = gapLayout === 'adjacent' ? 'Score' : presentation.label;
      const operatorTone = operator.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      th.className = `scoring-operator-header scoring-tone-${index % 5} scoring-operator-${operatorTone}`;
      th.title = `${presentation.label} (${operator}) weighted KPI points`;
      if (presentation.color) {
        th.style.backgroundColor = presentation.color;
        th.style.color = readableTextColor(presentation.color);
        th.style.setProperty('--operator-accent', presentation.color);
      }
      if (isReferenceOperator(tableData, operator)) markReferenceHeader(th);
      operatorHeader.append(th);
    };
    const appendGapHeader = operator => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.className = 'scoring-gap-header';
      th.dataset.column = 'gap';
      const operatorLabel = operatorPresentation(tableData, operator).label;
      th.textContent = gapLayout === 'adjacent' ? 'GAP' : `${operatorLabel} − ${baselineLabel}`;
      th.title = `${operator} weighted points minus baseline ${baseline} weighted points`;
      operatorHeader.append(th);
    };
    if (gapLayout === 'adjacent') {
      operators.forEach((operator, index) => {
        appendScoreHeader(operator, index);
        if (nonBaseline.includes(operator)) appendGapHeader(operator);
      });
    } else {
      operators.forEach(appendScoreHeader);
      nonBaseline.forEach(appendGapHeader);
    }
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
      if (item?.row_type === 'category') {
        tr.classList.add('scoring-category-subtotal');
        tr.style.fontWeight = '700';
      }
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
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      appendScoreGapCells(operators, nonBaseline, gapLayout,
        (operator, operatorIndex) => addMatrixScoreCell(
          tr, operatorValue(values, operator), `scoring-tone-${operatorIndex % 5}`, item?.row_type === 'category',
        ),
        operator => addMatrixGapCell(tr, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], '')),
      );
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
      label.textContent = total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
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
      const gaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
      const gapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      appendScoreGapCells(operators, nonBaseline, gapLayout,
        operator => addMatrixScoreCell(row, operatorValue(values, operator), '', true),
        operator => addMatrixGapCell(row, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], '')),
      );
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

  function hierarchyColumnEntries(tableData, styleSource = tableData, includeReference = true) {
    const sourceColumns = Array.isArray(tableData?.hierarchy_columns) && tableData.hierarchy_columns.length
      ? tableData.hierarchy_columns
      : (Array.isArray(styleSource?.hierarchy_columns) ? styleSource.hierarchy_columns : []);
    const byId = new Map(sourceColumns.map(column => [String(column?.id ?? ''), column]));
    const ids = Array.isArray(tableData?.operators) ? tableData.operators.map(String) : sourceColumns.map(column => String(column?.id ?? ''));
    const columns = ids.map((id, index) => ({...(byId.get(id) || {}), id, styleSource, sourceIndex: index}));
    columns.sort((left, right) => {
      const leftStyle = firstValue(styleSource?.operator_styles || {}, [left.id], {});
      const rightStyle = firstValue(styleSource?.operator_styles || {}, [right.id], {});
      const leftPosition = Number(firstValue(leftStyle, ['position'], left.sourceIndex));
      const rightPosition = Number(firstValue(rightStyle, ['position'], right.sourceIndex));
      return leftPosition - rightPosition || left.sourceIndex - right.sourceIndex;
    });
    return columns.filter(column => includeReference || !hierarchyColumnIsReference(column));
  }

  function hierarchyColumnIsReference(column) {
    const style = firstValue(column?.styleSource?.operator_styles || {}, [column?.id], {});
    return column?.is_reference === true || style?.is_reference === true
      || (column?.operator && isReferenceOperator(column.styleSource, column.operator));
  }

  function hierarchyColumnOperator(column) {
    const style = firstValue(column?.styleSource?.operator_styles || {}, [column?.id], {});
    return String(column?.operator || style?.operator || column?.id || '');
  }

  function hierarchyLevelNames(tableData, columns) {
    const configured = Array.isArray(tableData?.hierarchy_levels) ? tableData.hierarchy_levels.map(String) : [];
    if (configured.length) return configured;
    for (const column of columns) {
      if (Array.isArray(column?.path) && column.path.length) return column.path.map(item => String(item?.level || 'Level'));
    }
    return [];
  }

  function hierarchyPathEntry(column, depth, levels) {
    const path = Array.isArray(column?.path) ? column.path : [];
    const expectedLevel = levels[depth] || '';
    const entry = path.find(item => String(item?.level || '') === expectedLevel) || path[depth] || {};
    return {
      level: String(entry?.level || expectedLevel || `Level ${depth + 1}`),
      value: String(entry?.value ?? ''),
    };
  }

  function hierarchyPathValueLabel(column) {
    const path = Array.isArray(column?.path) ? column.path : [];
    return path.map(entry => {
      const value = String(entry?.value ?? '').trim();
      return value || 'Not specified';
    }).join(' · ');
  }

  function hierarchyPathFullLabel(column) {
    const path = Array.isArray(column?.path) ? column.path : [];
    return String(column?.label || path.map(entry => {
      const level = String(entry?.level || 'Level');
      const value = String(entry?.value ?? '').trim() || 'Not specified';
      return `${level}: ${value}`;
    }).join(' · '));
  }

  function appendHierarchyAxisBands(svg, categories, levels, columnsById, categoryStarts, step, baselineY, left, right) {
    if (!levels.length || !categories.length) return;
    const rowHeight = 23;
    const top = baselineY + 16;
    const width = Math.max(0, right - left);
    svg.append(svgElement(svg, 'rect', {x: left, y: top, width, height: rowHeight * levels.length, fill: '#ffffff'}));
    for (let rowIndex = 0; rowIndex < levels.length; rowIndex += 1) {
      const depth = levels.length - rowIndex - 1;
      const y = top + rowIndex * rowHeight;
      if (rowIndex % 2) svg.append(svgElement(svg, 'rect', {x: left, y, width, height: rowHeight, fill: '#f6f8f8'}));
      svg.append(svgElement(svg, 'line', {x1: left, x2: right, y1: y + rowHeight, y2: y + rowHeight, stroke: '#cbd6d9', 'stroke-width': 1}));
      let start = 0;
      while (start < categories.length) {
        const firstColumn = columnsById.get(String(categories[start]));
        const prefix = firstColumn ? hierarchyPrefixKey(firstColumn, depth, levels) : JSON.stringify(['missing', categories[start]]);
        let end = start + 1;
        while (end < categories.length) {
          const column = columnsById.get(String(categories[end]));
          const key = column ? hierarchyPrefixKey(column, depth, levels) : JSON.stringify(['missing', categories[end]]);
          if (key !== prefix) break;
          end += 1;
        }
        const firstStart = categoryStarts.get(String(categories[start]));
        const lastStart = categoryStarts.get(String(categories[end - 1]));
        const x1 = firstStart ?? left + start * step;
        const x2 = (lastStart ?? left + (end - 1) * step) + step;
        const entry = firstColumn ? hierarchyPathEntry(firstColumn, depth, levels) : {level: levels[depth], value: ''};
        const value = entry.value || 'Not specified';
        const groupWidth = x2 - x1;
        const maxCharacters = Math.max(5, Math.min(34, Math.floor(groupWidth / 7)));
        const lines = wrappedSvgLabelLines(value, maxCharacters, 2);
        const label = svgElement(svg, 'text', {
          x: x1 + groupWidth / 2,
          y: y + rowHeight / 2 + (lines.length > 1 ? -3 : 4),
          'text-anchor': 'middle',
          class: 'scoring-chart-hierarchy-label',
          'aria-label': `${entry.level}: ${value}`,
        });
        label.setAttribute('fill', '#334b58');
        label.setAttribute('font-size', '11');
        label.setAttribute('font-weight', '650');
        label.setAttribute('pointer-events', 'auto');
        lines.forEach((line, lineIndex) => {
          const span = svgElement(svg, 'tspan', {x: x1 + groupWidth / 2, dy: lineIndex ? '11' : '0'});
          span.textContent = line;
          label.append(span);
        });
        const title = svgElement(svg, 'title');
        title.textContent = firstColumn ? hierarchyPathFullLabel(firstColumn) : `${entry.level}: ${value}`;
        label.append(title);
        svg.append(label);
        svg.append(svgElement(svg, 'line', {x1, x2: x1, y1: y, y2: y + rowHeight, stroke: '#cbd6d9', 'stroke-width': 1}));
        start = end;
      }
      const lastCategoryStart = categoryStarts.get(String(categories[categories.length - 1]));
      const lastX = (lastCategoryStart ?? left + (categories.length - 1) * step) + step;
      svg.append(svgElement(svg, 'line', {x1: lastX, x2: lastX, y1: y, y2: y + rowHeight, stroke: '#cbd6d9', 'stroke-width': 1}));
    }
  }

  function hierarchyPrefixKey(column, depth, levels) {
    return JSON.stringify(Array.from({length: depth + 1}, (_, index) => {
      const entry = hierarchyPathEntry(column, index, levels);
      return [entry.level, entry.value];
    }));
  }

  function appendHierarchyHeaders(thead, tableData, columns, fixedHeadings, blocks) {
    const levels = hierarchyLevelNames(tableData, columns);
    const depth = Math.max(levels.length, ...columns.map(column => Array.isArray(column.path) ? column.path.length : 0));
    const headerLevels = levels.length ? levels : Array.from({length: depth}, (_, index) => `Level ${index + 1}`);
    const firstRow = document.createElement('tr');
    for (const [title, key, className = ''] of fixedHeadings) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.rowSpan = depth + 1;
      th.dataset.column = key;
      th.textContent = title;
      if (className) th.className = className;
      firstRow.append(th);
    }
    for (const block of blocks) {
      if (!block.columns.length) continue;
      const th = document.createElement('th');
      th.scope = 'colgroup';
      th.colSpan = block.columns.length;
      th.className = `scoring-column-group ${block.className || ''}`.trim();
      th.textContent = block.label;
      firstRow.append(th);
    }
    thead.append(firstRow);

    for (let depthIndex = 0; depthIndex < depth; depthIndex += 1) {
      const row = document.createElement('tr');
      for (const block of blocks) {
        if (!block.columns.length) continue;
        let start = 0;
        while (start < block.columns.length) {
          const key = hierarchyPrefixKey(block.columns[start], depthIndex, headerLevels);
          let end = start + 1;
          while (end < block.columns.length && hierarchyPrefixKey(block.columns[end], depthIndex, headerLevels) === key) end += 1;
          const groupedColumns = block.columns.slice(start, end);
          const entry = hierarchyPathEntry(groupedColumns[0], depthIndex, headerLevels);
          const th = document.createElement('th');
          th.scope = groupedColumns.length > 1 ? 'colgroup' : 'col';
          th.colSpan = groupedColumns.length;
          th.className = `scoring-hierarchy-header ${block.headerClass || ''}`.trim();
          th.dataset.column = block.column || 'hierarchy';
          th.dataset.hierarchyLevel = entry.level;
          th.dataset.hierarchyDepth = String(depthIndex);
          th.textContent = entry.value || 'Not specified';
          th.title = `${entry.level}: ${entry.value || 'Not specified'}`;
          th.setAttribute('aria-label', `${entry.level}: ${entry.value || 'Not specified'}`);
          if (depthIndex === depth - 1 && groupedColumns.length === 1) {
            th.classList.add('scoring-operator-header');
            const column = groupedColumns[0];
            const presentation = operatorPresentation(column.styleSource, column.id);
            const fullLabel = hierarchyPathFullLabel(column) || presentation.label || th.textContent;
            th.title = fullLabel;
            th.setAttribute('aria-label', fullLabel);
            if (presentation.color) th.style.setProperty('--operator-accent', presentation.color);
            if (hierarchyColumnIsReference(column)) {
              markReferenceHeader(th);
              th.title = `${fullLabel} is the reference operator`;
            }
          }
          row.append(th);
          start = end;
        }
      }
      thead.append(row);
    }
    return {levels: headerLevels, depth};
  }

  function appendHierarchyMatrixTable(pane, tableData) {
    const rows = Array.isArray(tableData?.rows) ? tableData.rows : [];
    const allColumns = hierarchyColumnEntries(tableData);
    const nonBaseline = allColumns.filter(column => !hierarchyColumnIsReference(column));
    const showKpiValues = Boolean(showKpiValuesToggle?.checked);
    const gapLayout = selectedGapLayout();
    const blocks = [
      ...(showKpiValues ? [{label: 'KPI Value', className: 'scoring-kpi-value-group', headerClass: 'scoring-kpi-value-header', column: 'kpi-value', columns: allColumns}] : []),
      ...(gapLayout === 'adjacent'
        ? allColumns.flatMap(column => [
          {label: 'Score', className: 'scoring-score-group', headerClass: 'scoring-score-header', column: 'score', columns: [column]},
          ...(!hierarchyColumnIsReference(column)
            ? [{label: 'GAP', className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns: [column]}]
            : []),
        ])
        : [
          {label: 'Score', className: 'scoring-score-group', headerClass: 'scoring-score-header', column: 'score', columns: allColumns},
          {label: 'GAP', className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns: nonBaseline},
        ]),
    ];
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-hierarchy-table';
    const thead = document.createElement('thead');
    appendHierarchyHeaders(thead, tableData, allColumns, [
      ['Category', 'category'], ['KPI', 'kpi'], ['Score weight (%)', 'weight', 'scoring-weight-header'], ['Max score', 'maximum', 'scoring-maximum-header'],
    ], blocks);
    const tbody = document.createElement('tbody');
    for (let index = 0; index < rows.length; index += 1) {
      const item = rows[index];
      const row = document.createElement('tr');
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
      const category = String(item?.category || 'Other');
      if (index === 0 || String(rows[index - 1]?.category || 'Other') !== category) {
        let span = 1;
        while (index + span < rows.length && String(rows[index + span]?.category || 'Other') === category) span += 1;
        const categoryCell = document.createElement('td');
        categoryCell.className = 'scoring-category-cell';
        categoryCell.rowSpan = span;
        categoryCell.textContent = category;
        categoryCell.dataset.column = 'category';
        row.append(categoryCell);
      }
      const kpi = document.createElement('td');
      kpi.dataset.column = 'kpi';
      kpi.textContent = String(item?.kpi || item?.kpi_code || 'N/A');
      kpi.title = String(item?.kpi_code || item?.kpi || '');
      row.append(kpi);
      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(item?.weight_percent);
      row.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(item?.max_points);
      row.append(maximum);
      const values = item?.values && typeof item.values === 'object' ? item.values : {};
      if (showKpiValues) {
        for (const column of allColumns) {
          const cell = document.createElement('td');
          const operatorCell = operatorValue(values, column.id);
          const rawValue = operatorCell && typeof operatorCell === 'object' ? firstValue(operatorCell, ['value', 'raw_value', 'kpi_value'], null) : null;
          const presentation = operatorPresentation(column.styleSource, column.id);
          const unit = firstValue(item, ['unit', 'units', 'measurement_unit'], '');
          cell.className = 'scoring-kpi-value-cell';
          cell.dataset.column = 'kpi-value';
          cell.textContent = formatRawKpiValue(rawValue);
          cell.dataset.numeric = rawValue !== null && rawValue !== undefined && String(rawValue).trim() !== '' && Number.isFinite(Number(rawValue)) ? 'true' : 'false';
          cell.title = `Raw ${item?.kpi || item?.kpi_code || 'KPI'} measurement for ${presentation.label}${unit ? ` (${unit})` : ''}: ${formatRawKpiValue(rawValue)}`;
          row.append(cell);
        }
      }
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      appendScoreGapCells(allColumns, nonBaseline, gapLayout,
        (column, columnIndex) => addMatrixScoreCell(
          row, operatorValue(values, column.id), `scoring-tone-${columnIndex % 5}`, item?.row_type === 'category',
        ),
        column => addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], '')),
      );
      tbody.append(row);
    }
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
      label.textContent = total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
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
        allColumns.forEach(() => {
          const cell = document.createElement('td');
          cell.className = 'scoring-kpi-value-cell';
          cell.dataset.column = 'kpi-value';
          cell.textContent = 'N/A';
          cell.title = 'A single raw KPI measurement does not apply to the weighted total.';
          row.append(cell);
        });
      }
      const gaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
      const gapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      appendScoreGapCells(allColumns, nonBaseline, gapLayout,
        column => addMatrixScoreCell(row, operatorValue(values, column.id), '', true),
        column => addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], '')),
      );
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No KPI rows are available for this hierarchy.';
      pane.append(empty);
    }
  }

  function renderHierarchyScoringViews(pane, tableData, thresholdLegend = []) {
    pane.replaceChildren();
    if (!tableData) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No hierarchical scoring table is available for this environment.';
      pane.append(empty);
      return;
    }
    appendContextHeader(pane, tableData, 'score');
    appendThresholdLegend(pane, thresholdLegend.length ? thresholdLegend : tableData?.threshold_legend);
    appendScoringGapScale(pane, tableData);
    appendHierarchyMatrixTable(pane, tableData);
  }

  function renderHierarchyGapViews(pane, tableData, scoreTable) {
    pane.replaceChildren();
    if (!tableData) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No hierarchical GAP table is available for this environment.';
      pane.append(empty);
      return;
    }
    const styleSource = scoreTable || tableData;
    const baselineRaw = String(tableData.baseline_operator || 'the reference operator');
    const baseline = canonicalOperatorName(baselineRaw) || baselineRaw;
    const allColumns = hierarchyColumnEntries(tableData, styleSource, false)
      .filter(column => !hierarchyColumnIsReference(column)
        && hierarchyColumnOperator(column).toLocaleLowerCase() !== baseline.toLocaleLowerCase());
    const operators = [...new Set(allColumns.map(hierarchyColumnOperator).filter(Boolean))];
    const comparisonStateKey = `hierarchy-gap-operator:${comparisonIdentity(tableData, 'hierarchy-gap')}`;
    let comparison = contextSelections.get(comparisonStateKey) || 'all';
    const selectedOperator = comparison.startsWith('operator:') ? comparison.slice('operator:'.length) : null;
    if (selectedOperator && !operators.includes(selectedOperator)) comparison = 'all';
    contextSelections.set(comparisonStateKey, comparison);
    const columns = comparison === 'all'
      ? allColumns
      : allColumns.filter(column => hierarchyColumnOperator(column) === selectedOperator);
    const rows = Array.isArray(tableData.rows) ? tableData.rows : [];
    const comparisonLabel = comparison === 'all' ? `All vs ${baseline}` : `${selectedOperator} vs ${baseline}`;
    const scaleRows = rows.flatMap(item => columns.map(column => ({gap_points: firstValue(item?.gaps || {}, [column.id], null)})))
      .filter(item => item.gap_points !== null && item.gap_points !== undefined && Number.isFinite(Number(item.gap_points)));
    appendContextHeader(pane, tableData, 'gap', `GAP Analysis — ${comparisonLabel}`);
    if (operators.length) {
      const controls = document.createElement('div');
      controls.className = 'scoring-comparison-controls scoring-gap-comparison-controls';
      const label = document.createElement('label');
      label.textContent = 'Operator comparison';
      const select = document.createElement('select');
      select.dataset.hierarchyGapOperator = '';
      select.dataset.hierarchyGapStateKey = comparisonStateKey;
      select.setAttribute('aria-label', 'Choose all operators or one operator to compare with the reference');
      const allOption = document.createElement('option');
      allOption.value = 'all';
      allOption.textContent = `All vs ${baseline}`;
      allOption.selected = comparison === 'all';
      select.append(allOption);
      for (const operator of operators) {
        const option = document.createElement('option');
        option.value = `operator:${operator}`;
        option.textContent = `${operator} vs ${baseline}`;
        option.selected = comparison === option.value;
        select.append(option);
      }
      label.append(select);
      controls.append(label);
      pane.append(controls);
    }
    const note = document.createElement('p');
    note.className = 'scoring-context-note';
    note.textContent = `KPI GAP compares ${comparison === 'all' ? 'each hierarchy leaf' : selectedOperator} with ${baseline} at the same context. Category and final GAP rows show the arithmetic mean of valid KPI GAPs.`;
    pane.append(note);
    if (!columns.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No operators can be compared with the selected reference operator.';
      pane.append(empty);
      return;
    }
    appendPriorityGapScale(pane, tableData, scaleRows);

    const blocks = [{label: comparisonLabel, className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns}];
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-priority-table scoring-gap-summary-table scoring-hierarchy-table';
    const thead = document.createElement('thead');
    appendHierarchyHeaders(thead, styleSource, columns, [
      ['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type'],
    ], blocks);
    const tbody = document.createElement('tbody');
    for (let index = 0; index < rows.length; index += 1) {
      const item = rows[index];
      const row = document.createElement('tr');
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
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
      typeCell.textContent = item?.row_type === 'category'
        ? '—' : (!kpiType || kpiType.toLowerCase() === 'unknown' ? 'Not classified' : kpiType);
      if (kpiType.toLowerCase() === 'reliable') typeCell.dataset.kpiType = 'reliable';
      row.append(typeCell);
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      for (const column of columns) addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], ''));
      tbody.append(row);
    }
    table.append(thead, tbody);
    const total = tableData.total && typeof tableData.total === 'object' ? tableData.total : {};
    const totalGaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
    if (Object.keys(totalGaps).length) {
      const tfoot = document.createElement('tfoot');
      const row = document.createElement('tr');
      const label = document.createElement('th');
      label.scope = 'row';
      label.colSpan = 3;
      label.textContent = total.gap_label || 'Total signed GAP';
      row.append(label);
      const totalGapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      for (const column of columns) addMatrixGapCell(row, firstValue(totalGaps, [column.id], null), firstValue(totalGapColors, [column.id], ''));
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No KPI rows are available for this hierarchy comparison.';
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
    const rows = (Array.isArray(selected?.rows) ? selected.rows : []).filter(row => (
      row?.row_type === 'category' || row?.row_type === 'kpi'
      || (row?.gap_points !== null && row?.gap_points !== undefined && String(row.gap_points).trim() !== '' && Number.isFinite(Number(row.gap_points)))
    ));
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
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
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
          cell.textContent = key === 'type' && item?.row_type === 'category'
            ? '—'
            : key === 'type' && (value === null || value === undefined || value === '' || normalizedType === 'unknown')
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
      const label = selected.expanded_total?.gap_label || selected.total?.gap_label || 'Total signed GAP';
      summary.textContent = `${label} (${operator} − ${baseline}): ${formatMatrixNumber(selected.total_gap_points, true)} points.`;
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
    gapNote.textContent = `KPI GAP = compared operator weighted points minus ${baseline} weighted points for each KPI. Category and final GAP rows show the arithmetic mean of valid KPI GAPs.`;
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
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
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
      typeCell.textContent = item?.row_type === 'category'
        ? '—' : (!kpiType || kpiType.toLowerCase() === 'unknown' ? 'Not classified' : kpiType);
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
      labelCell.textContent = total.gap_label || 'Total signed GAP';
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

  function wrappedSvgLabelLines(value, maxLength = 22, maxLines = 2) {
    const lines = [];
    let current = '';
    for (const word of String(value).split(/\s+/)) {
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > maxLength && current) {
        lines.push(current);
        current = word;
      } else current = candidate;
    }
    if (current) lines.push(current);
    if (lines.length > maxLines) {
      const last = `${lines.slice(maxLines - 1).join(' ').slice(0, maxLength - 1)}…`;
      lines.splice(maxLines - 1, lines.length - maxLines + 1, last);
    }
    return lines;
  }

  function makeSvgChart(title, rows, operatorTable, options = {}) {
    const stacked = Boolean(options.stacked);
    const categories = Array.isArray(options.categoryOrder)
      ? [...new Set([...options.categoryOrder.map(String), ...rows.map(row => String(row.category))])]
      : [...new Set(rows.map(row => row.category))];
    const presentSeries = new Set(rows.map(row => row.series));
    const mappedOrder = Array.isArray(operatorTable?.operators) ? operatorTable.operators.map(String) : [];
    const requestedSeriesOrder = Array.isArray(options.seriesOrder) ? options.seriesOrder.map(String) : mappedOrder;
    const series = [...requestedSeriesOrder.filter(name => presentSeries.has(name)),
      ...[...presentSeries].filter(name => !requestedSeriesOrder.includes(name)).sort((left, right) => left.localeCompare(right))];
    const hierarchyColumns = Array.isArray(options.hierarchyColumns)
      ? options.hierarchyColumns
      : Object.values(options.hierarchyColumns || {});
    const hierarchyColumnsById = new Map(hierarchyColumns.map(column => [String(column?.id ?? ''), column]));
    const hierarchyLevels = Array.isArray(options.hierarchyLevels) ? options.hierarchyLevels.map(String) : [];
    const hasHierarchyAxis = stacked && hierarchyLevels.length > 0 && hierarchyColumnsById.size > 0;
    const width = Math.max(1180, categories.length * (stacked ? 150 : Math.max(168, series.length * 38 + 22)) + 150);
    const height = 700;
    const left = 86, right = 28, bottom = Math.max(150, 24 + (hasHierarchyAxis ? hierarchyLevels.length * 23 : 0));
    const maxValue = stacked
      ? Math.max(0, ...categories.map(category => series.reduce((sum, seriesName) => {
        const row = rows.find(candidate => String(candidate.category) === String(category) && String(candidate.series) === seriesName);
        const value = row?.value === null || row?.value === undefined || String(row.value).trim() === '' ? Number.NaN : Number(row.value);
        return sum + (Number.isFinite(value) ? Math.max(0, value) : 0);
      }, 0)))
      : Math.max(0, ...rows.map(row => Number(row.value)).filter(Number.isFinite));
    const scaleMaximum = maxValue > 0 ? maxValue * 1.16 : 1;
    const groupKeys = categories.map(category => String(options.groupKeyForCategory?.(category) || ''));
    const groupTransitions = hasHierarchyAxis
      ? groupKeys.slice(1).filter((key, index) => key && groupKeys[index] && key !== groupKeys[index]).length : 0;
    const categoryGroupGap = hasHierarchyAxis ? Math.max(0, Number(options.categoryGroupGap) || 14) : 0;
    const step = Math.max(1, (width - left - right - categoryGroupGap * groupTransitions) / Math.max(categories.length, 1));
    const categoryStarts = new Map();
    let categoryCursor = left;
    categories.forEach((category, index) => {
      if (index && groupKeys[index] && groupKeys[index - 1] && groupKeys[index] !== groupKeys[index - 1]) categoryCursor += categoryGroupGap;
      categoryStarts.set(String(category), categoryCursor);
      categoryCursor += step;
    });
    const fallbackColors = ['#14867d', '#df7a45', '#5a82aa', '#8b63b1', '#b49a32'];
    const presentations = new Map(series.map((name, index) => {
      const presentation = options.seriesStyles?.[name] || operatorPresentation(operatorTable, name);
      return [name, {...presentation, chartColor: presentation.color || fallbackColors[index % fallbackColors.length]}];
    }));
    const legendEntries = Array.isArray(options.legendEntries)
      ? options.legendEntries
      : series.map(name => ({label: presentations.get(name).label, color: presentations.get(name).chartColor, title: name}));
    const legendRows = [];
    for (const entry of legendEntries) {
      const label = String(entry?.label || '');
      const entryWidth = 34 + label.length * 7.2;
      let row = legendRows[legendRows.length - 1];
      if (!row || (row.width + entryWidth > width - left - right && row.entries.length)) {
        row = {width: 0, entries: []};
        legendRows.push(row);
      }
      row.entries.push({...entry, label, entryWidth});
      row.width += entryWidth;
    }
    const top = Math.max(76, 42 + legendRows.length * 20);
    const chartHeight = height - top - bottom;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', title);

    legendRows.forEach((row, rowIndex) => {
      let x = left;
      for (const entry of row.entries) {
        const color = safeHexColor(entry.color) || fallbackColors[0];
        const swatch = document.createElementNS(svg.namespaceURI, 'rect');
        swatch.setAttribute('x', String(x)); swatch.setAttribute('y', String(25 + rowIndex * 20)); swatch.setAttribute('width', '14'); swatch.setAttribute('height', '14');
        swatch.setAttribute('rx', '3'); swatch.setAttribute('fill', color);
        const legend = document.createElementNS(svg.namespaceURI, 'text');
        legend.setAttribute('x', String(x + 21)); legend.setAttribute('y', String(37 + rowIndex * 20));
        legend.setAttribute('class', 'scoring-chart-legend');
        legend.textContent = entry.label;
        const fullName = document.createElementNS(svg.namespaceURI, 'title');
        fullName.textContent = String(entry.title || entry.label); legend.append(fullName);
        svg.append(swatch, legend);
        x += entry.entryWidth;
      }
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
    axisLabel.textContent = options.axisLabel || 'Weighted score (points)';
    svg.append(axisLabel);
    if (hasHierarchyAxis) {
      appendHierarchyAxisBands(svg, categories, hierarchyLevels, hierarchyColumnsById, categoryStarts, step, top + chartHeight, left, width - right);
    }

    categories.forEach((category, categoryIndex) => {
      if (stacked) {
        const barWidth = Math.min(76, step * .58);
        const categoryStart = categoryStarts.get(String(category)) ?? left + step * categoryIndex;
        const x = categoryStart + (step - barWidth) / 2;
        let stackY = baselineY;
        let hasValue = false;
        let complete = true;
        let total = 0;
        for (const [seriesIndex, seriesName] of series.entries()) {
          const row = rows.find(candidate => String(candidate.category) === String(category) && String(candidate.series) === seriesName);
          if (!row) continue;
          const numeric = row.value === null || row.value === undefined || String(row.value).trim() === '' ? Number.NaN : Number(row.value);
          if (!Number.isFinite(numeric)) {
            complete = false;
            continue;
          }
          hasValue = true;
          total += numeric;
          complete = complete && row.complete !== false;
          const segmentHeight = Math.max(0, numeric / scaleMaximum * chartHeight);
          const segmentY = stackY - segmentHeight;
          const configuredSegmentColor = typeof options.segmentColor === 'function'
            ? safeHexColor(options.segmentColor(category, seriesName, seriesIndex, row)) : '';
          const color = configuredSegmentColor || presentations.get(seriesName).chartColor;
          const rect = document.createElementNS(svg.namespaceURI, 'rect');
          rect.setAttribute('x', String(x)); rect.setAttribute('y', String(segmentY));
          rect.setAttribute('width', String(barWidth)); rect.setAttribute('height', String(Math.max(0, segmentHeight)));
          rect.setAttribute('fill', color);
          if (hasHierarchyAxis) {
            rect.setAttribute('stroke', '#ffffff');
            rect.setAttribute('stroke-width', '.5');
          }
          const visibleCategory = options.categoryLabels?.[category] || category;
          const fullCategory = options.categoryTooltips?.[category] || visibleCategory;
          rect.setAttribute('aria-label', `${fullCategory}, ${presentations.get(seriesName).label}: ${numeric}`);
          const segmentTitle = document.createElementNS(svg.namespaceURI, 'title');
          segmentTitle.textContent = `${fullCategory} · ${presentations.get(seriesName).label}: ${numeric.toLocaleString(undefined, {maximumFractionDigits: 3})}${row.complete === false ? ' (partial coverage)' : ''}`;
          rect.append(segmentTitle);
          svg.append(rect);
          if (segmentHeight >= 24) {
            const segmentLabel = document.createElementNS(svg.namespaceURI, 'text');
            segmentLabel.setAttribute('x', String(x + barWidth / 2));
            segmentLabel.setAttribute('y', String(segmentY + segmentHeight / 2 + 4));
            segmentLabel.setAttribute('text-anchor', 'middle');
            segmentLabel.setAttribute('class', 'scoring-best-network-segment');
            segmentLabel.textContent = numeric.toLocaleString(undefined, {maximumFractionDigits: 1});
            svg.append(segmentLabel);
          }
          stackY = segmentY;
        }
        if (!hasValue) {
          const unavailable = document.createElementNS(svg.namespaceURI, 'text');
          unavailable.setAttribute('x', String(x + barWidth / 2));
          unavailable.setAttribute('y', String(baselineY - 7));
          unavailable.setAttribute('text-anchor', 'middle');
          unavailable.setAttribute('class', 'scoring-chart-unavailable');
          unavailable.textContent = 'N/A';
          svg.append(unavailable);
        } else {
          const totalLabel = document.createElementNS(svg.namespaceURI, 'text');
          totalLabel.setAttribute('x', String(x + barWidth / 2));
          totalLabel.setAttribute('y', String(Math.max(top + 14, stackY - 7)));
          totalLabel.setAttribute('text-anchor', 'middle');
          totalLabel.setAttribute('class', 'scoring-chart-value');
          totalLabel.textContent = `${total.toLocaleString(undefined, {maximumFractionDigits: 1})}${complete ? '' : '*'}`;
          svg.append(totalLabel);
        }
      } else {
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
      }
      if (!hasHierarchyAxis) {
        const lines = [];
        const visibleCategory = options.categoryLabels?.[category] || category;
        const fullCategory = options.categoryTooltips?.[category] || visibleCategory;
        lines.push(...wrappedSvgLabelLines(visibleCategory, stacked ? 24 : 22, stacked ? 4 : 2));
        const label = document.createElementNS(svg.namespaceURI, 'text');
        const categoryStart = categoryStarts.get(String(category)) ?? left + step * categoryIndex;
        const labelX = categoryStart + step / 2;
        label.setAttribute('x', String(labelX)); label.setAttribute('y', String(baselineY + 24));
        label.setAttribute('text-anchor', 'middle'); label.setAttribute('class', 'scoring-chart-category');
        lines.forEach((line, lineIndex) => {
          const span = document.createElementNS(svg.namespaceURI, 'tspan');
          span.setAttribute('x', String(labelX)); span.setAttribute('dy', lineIndex ? '1.15em' : '0');
          span.textContent = line;
          label.append(span);
        });
        const fullCategoryTitle = document.createElementNS(svg.namespaceURI, 'title');
        fullCategoryTitle.textContent = fullCategory; label.append(fullCategoryTitle);
        svg.append(label);
      }
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

  function renderHierarchyCharts(pane, tableData) {
    pane.replaceChildren();
    if (!tableData) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No hierarchical chart is available for this environment.';
      pane.append(empty);
      return;
    }
    const columns = hierarchyColumnEntries(tableData);
    const sourceRows = scoreChartRows([tableData]);
    const rows = sourceRows.map(row => ({
      category: String(row.operator),
      series: String(row.category),
      value: row.weighted_points,
      complete: row.complete,
    }));
    if (!rows.length || !columns.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No chart rows are available for this hierarchy.';
      pane.append(empty);
      return;
    }
    const categoryLabels = Object.fromEntries(columns.map(column => [
      column.id,
      hierarchyPathValueLabel(column) || operatorPresentation(column.styleSource, column.id).label,
    ]));
    const categoryTooltips = Object.fromEntries(columns.map(column => [
      column.id,
      hierarchyPathFullLabel(column) || operatorPresentation(column.styleSource, column.id).label,
    ]));
    const kpiCategories = [...new Set(sourceRows.map(row => String(row.category)))];
    const operatorLegend = [];
    const seenOperators = new Set();
    const operatorColors = new Map();
    for (const column of columns) {
      const style = firstValue(tableData?.operator_styles || {}, [column.id], {});
      const operator = String(column.operator || style.operator || operatorPresentation(column.styleSource, column.id).label);
      const presentation = operatorPresentation(column.styleSource, column.id);
      const color = presentation.color || ['#14867d', '#df7a45', '#5a82aa', '#8b63b1'][operatorColors.size % 4];
      operatorColors.set(operator, color);
      if (seenOperators.has(operator)) continue;
      seenOperators.add(operator);
      operatorLegend.push({
        label: `${operator}${style.is_reference === true || column.is_reference === true ? ' (Reference)' : ''}`,
        color,
        title: `${operator}${style.is_reference === true || column.is_reference === true ? ' is the reference operator.' : ''} Segment shades identify KPI categories; hover a segment for its category and score.`,
      });
    }
    const categoryLegendColor = operatorLegend[0]?.color || '#365F91';
    const categoryLegend = kpiCategories.map((category, index) => ({
      label: category,
      color: hierarchyChartColor(categoryLegendColor, index, kpiCategories.length),
      title: `${category}: segment shade ${index + 1}. Each operator keeps its mapped base color.`,
    }));
    const seriesStyles = Object.fromEntries(kpiCategories.map(category => [category, {label: category}]));
    appendContextHeader(pane, tableData, 'score', 'Scoring Chart');
    const chart = makeSvgChart('Weighted score by operator and aggregation', rows, tableData, {
      stacked: true,
      categoryOrder: columns.map(column => column.id),
      categoryLabels,
      categoryTooltips,
      hierarchyLevels: tableData.hierarchy_levels,
      hierarchyColumns: columns,
      groupKeyForCategory: leafId => hierarchyColumnOperator(columns.find(column => column.id === leafId)),
      categoryGroupGap: 14,
      seriesOrder: kpiCategories,
      seriesStyles,
      legendEntries: [...operatorLegend, ...categoryLegend],
      segmentColor: (leafId, _category, categoryIndex) => {
        const column = columns.find(item => item.id === leafId);
        const operator = String(column?.operator || firstValue(tableData?.operator_styles || {}, [leafId], {}).operator || '');
        return hierarchyChartColor(operatorColors.get(operator) || '#365F91', categoryIndex, kpiCategories.length);
      },
      axisLabel: 'Weighted score points',
    });
    chart.style.minWidth = `${chart.viewBox.baseVal.width}px`;
    pane.append(makeExpandableChartCard('Weighted score by operator and aggregation', contextLabel(tableData.context), chart));
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

  function hierarchyChartColor(color, categoryIndex, categoryCount = 7) {
    const safe = safeHexColor(color) || '#365F91';
    const tint = .72 * Math.max(0, categoryIndex) / Math.max(1, categoryCount - 1);
    const channels = [1, 3, 5].map(offset => Number.parseInt(safe.slice(offset, offset + 2), 16));
    return `#${channels.map(channel => Math.round(channel + (255 - channel) * tint).toString(16).padStart(2, '0')).join('')}`;
  }

  function makeBestNetworkBars(tableData, data) {
    const hierarchyLevels = Array.isArray(tableData?.hierarchy_levels) ? tableData.hierarchy_levels.map(String) : [];
    const hierarchyColumns = Array.isArray(tableData?.hierarchy_columns) ? tableData.hierarchy_columns : [];
    const hierarchyColumnsById = new Map(hierarchyColumns.map(column => [String(column?.id ?? ''), column]));
    const hasHierarchyAxis = hierarchyLevels.length > 0 && hierarchyColumnsById.size > 0;
    const groupKeys = data.operators.map(operator => hierarchyColumnOperator(hierarchyColumnsById.get(operator)));
    const groupTransitions = hasHierarchyAxis
      ? groupKeys.slice(1).filter((key, index) => key && groupKeys[index] && key !== groupKeys[index]).length : 0;
    const categoryGroupGap = hasHierarchyAxis ? 14 : 0;
    const width = Math.max(980, data.operators.length * 190 + 170);
    const height = 620;
    const left = 92, right = 36, top = 72, bottom = Math.max(124, 32 + (hasHierarchyAxis ? hierarchyLevels.length * 23 : 0));
    const plotHeight = height - top - bottom;
    const maxAllocation = data.allocation.Voice + data.allocation.Data;
    const maxActual = Math.max(0, ...data.operators.map(operator => ['Voice', 'Data'].reduce((sum, kind) => sum + (data.totals[operator][kind].value ?? 0), 0)));
    const scaleValue = maxActual > 0 ? maxActual : maxAllocation;
    const scaleMaximum = scaleValue > 0 ? scaleValue * 1.13 : 1;
    const step = Math.max(1, (width - left - right - categoryGroupGap * groupTransitions) / Math.max(data.operators.length, 1));
    const categoryStarts = new Map();
    let categoryCursor = left;
    data.operators.forEach((operator, index) => {
      if (index && groupKeys[index] && groupKeys[index - 1] && groupKeys[index] !== groupKeys[index - 1]) categoryCursor += categoryGroupGap;
      categoryStarts.set(operator, categoryCursor);
      categoryCursor += step;
    });
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg scoring-best-network-bars');
    svg.style.minWidth = `${width}px`;
    svg.style.maxWidth = 'none';
    svg.style.minHeight = '0';
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Voice and Data weighted points by operator');
    const barColors = new Map(data.operators.map((operator, index) => {
      const mapped = operatorPresentation(tableData, operator);
      const hierarchyColumn = Array.isArray(tableData?.hierarchy_columns)
        ? tableData.hierarchy_columns.find(column => String(column?.id) === operator) : null;
      return [operator, {
        label: hierarchyColumn ? hierarchyPathValueLabel(hierarchyColumn) : mapped.label,
        fullLabel: hierarchyColumn ? hierarchyPathFullLabel(hierarchyColumn) : mapped.label,
        color: mapped.color || ['#14867d', '#df7a45', '#5a82aa', '#8b63b1'][index % 4],
      }];
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
    if (hasHierarchyAxis) {
      appendHierarchyAxisBands(svg, data.operators, hierarchyLevels, hierarchyColumnsById, categoryStarts, step, top + plotHeight, left, width - right);
    }
    data.operators.forEach((operator, index) => {
      const presentation = barColors.get(operator);
      const barWidth = Math.min(92, step * .48);
      const x = (categoryStarts.get(operator) ?? left + step * index) + (step - barWidth) / 2;
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
        const rect = svgElement(svg, 'rect', {x, y: segmentY, width: barWidth, height: segmentHeight, ...(hasHierarchyAxis ? {} : {rx: 3}), fill: color});
        const tip = svgElement(svg, 'title');
        tip.textContent = `${presentation.fullLabel} · ${kind}: ${cell.value.toLocaleString(undefined, {maximumFractionDigits: 2})}${cell.complete ? '' : ' (partial coverage)'}`;
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
      if (!hasHierarchyAxis) {
        const operatorLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: baselineY + 28, 'text-anchor': 'middle', class: 'scoring-chart-category'});
        const labelLines = wrappedSvgLabelLines(presentation.label, 24, 1);
        labelLines.forEach((line, lineIndex) => {
          const span = svgElement(svg, 'tspan', {x: x + barWidth / 2, dy: lineIndex ? '1.15em' : '0'});
          span.textContent = line;
          operatorLabel.append(span);
        });
        const rawLabel = svgElement(svg, 'title');
        rawLabel.textContent = presentation.fullLabel;
        operatorLabel.append(rawLabel);
        svg.append(operatorLabel);
      }
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

  function renderBestNetworkChart(pane, scoreTables, hierarchyTable = null) {
    pane.replaceChildren();
    if (!hierarchyTable && !scoreTables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No Best Network chart is available for this environment.';
      pane.append(empty);
      return;
    }
    const selected = hierarchyTable || appendComparisonSelector(pane, scoreTables, 'score');
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

  const environmentOrder = ['DriveCity', 'DriveConnectionroad', 'Walk', 'Combined'];
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
    const combinedIsAvailable = tables.some(table => {
      if (environmentOf(table) !== 'Combined') return false;
      const required = Array.isArray(table.combined_required_environments) && table.combined_required_environments.length
        ? table.combined_required_environments
        : ['DriveCity', 'DriveConnectionroad'];
      return required.every(environment => actualByScope.get(scopeIdentity(table.context || {}))?.has(environment));
    });
    const ordered = [...available].sort((left, right) => {
      const leftIndex = environmentOrder.indexOf(left);
      const rightIndex = environmentOrder.indexOf(right);
      return (leftIndex < 0 ? environmentOrder.length : leftIndex) - (rightIndex < 0 ? environmentOrder.length : rightIndex) || left.localeCompare(right);
    });
    return ordered.length || combinedIsAvailable ? ['all', ...ordered] : [];
  }

  function environmentLabel(environment) {
    if (environment === 'all' || environment === 'Combined') return 'All Environments';
    if (environment === 'DriveCity') return 'Drive City';
    if (environment === 'DriveConnectionroad') return 'Drive Connection Road';
    if (environment === 'Walk') return 'Walk';
    return environment;
  }

  function syncResultEnvironment(tables) {
    const environments = availableScoreEnvironments(tables);
    if (!environments.length) {
      currentEffectiveEnvironment = null;
      environmentSelect.replaceChildren();
      environmentControl.hidden = true;
      return {environments, effective: null, fallback: null};
    }
    if (!environments.includes(selectedEnvironment)) {
      selectedEnvironment = 'all';
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
    const actual = environments.filter(environment => environment !== 'all');
    const combinedTables = tables.filter(table => environmentOf(table) === 'Combined');
    const combinedIsAvailable = combinedTables.some(table => {
      const required = Array.isArray(table.combined_required_environments) && table.combined_required_environments.length
        ? table.combined_required_environments : ['DriveCity', 'DriveConnectionroad'];
      const scope = scopeIdentity(table.context || {});
      const actualByScope = new Set(tables.filter(candidate => scopeIdentity(candidate.context || {}) === scope)
        .map(environmentOf));
      return required.every(environment => actualByScope.has(environment));
    }) || (!actual.length && combinedTables.length > 0);
    const effective = selectedEnvironment === 'all'
      ? (combinedIsAvailable ? 'Combined' : (actual[0] || null))
      : selectedEnvironment;
    currentEffectiveEnvironment = effective;
    return {environments, effective, fallback: selectedEnvironment === 'all' && effective && effective !== 'Combined' ? effective : null};
  }

  function chartRowsForEnvironment(source, scoreTables, effectiveEnvironment) {
    const rows = normalizeRows(source);
    if (!scoreTables.length) return rows;
    return rows.filter(row => {
      if (String(firstValue(row, ['environment'], '')) !== effectiveEnvironment) return false;
      return scoreTables.some(table => environmentOf(table) === effectiveEnvironment
        && comparisonScopeFields.every(field => String(firstValue(table.context || {}, [field], '') ?? '')
          === String(firstValue(row, [field], '') ?? '')));
    });
  }

  function renderResult(payload, job, panesToRender = [activeResultTab]) {
    currentResults = payload;
    currentResultsJobId = jobIdOf(job || payload.job || {}) || null;
    const shouldRenderPane = name => panesToRender.includes(name);
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
    const allHierarchyScoreTables = normalizeRows(views.hierarchy_score_tables ?? []);
    const allHierarchyGapTables = normalizeRows(views.hierarchy_gap_tables ?? []);
    const environmentSelection = syncResultEnvironment([...allScoreTables, ...allHierarchyScoreTables]);
    const effectiveEnvironment = environmentSelection.effective;
    const scoreTables = allScoreTables.filter(table => environmentOf(table) === effectiveEnvironment);
    const gapTables = allGapTables.filter(table => environmentOf(table) === effectiveEnvironment);
    const gapSummaryTables = allGapSummaryTables.filter(table => environmentOf(table) === effectiveEnvironment);
    const hierarchyScoreTable = allHierarchyScoreTables.find(table => environmentOf(table) === effectiveEnvironment) || null;
    const hierarchyGapTable = allHierarchyGapTables.find(table => environmentOf(table) === effectiveEnvironment) || null;
    const displayScoreTables = scoreTables.map(tableForSelectedMode);
    const displayGapTables = gapTables.map(tableForSelectedMode);
    const displayGapSummaryTables = gapSummaryTables.map(tableForSelectedMode);
    const displayHierarchyScoreTable = tableForSelectedMode(hierarchyScoreTable);
    const displayHierarchyGapTable = tableForSelectedMode(hierarchyGapTable);
    const thresholdLegend = normalizeRows(views.threshold_legend ?? payload.threshold_legend ?? []);
    const totalsRows = normalizeRows(payload.totals ?? payload.scoring_totals ?? []);
    const detailRows = normalizeRows(scoringRows);
    const hasScoringViews = Array.isArray(views.score_tables) || Array.isArray(payload.score_tables) || Array.isArray(payload.scoring_views?.score_tables);
    const hasGapViews = Array.isArray(views.gap_tables) || Array.isArray(payload.gap_tables) || Array.isArray(payload.scoring_views?.gap_tables)
      || Array.isArray(views.gap_summary_tables) || Array.isArray(payload.gap_summary_tables) || Array.isArray(payload.scoring_views?.gap_summary_tables);
    if (shouldRenderPane('scoring')) {
      if (displayHierarchyScoreTable) {
        renderHierarchyScoringViews(scoringPane, displayHierarchyScoreTable, thresholdLegend);
      } else if (hasScoringViews) {
        renderScoringViews(scoringPane, displayScoreTables, thresholdLegend);
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
    }
    if (shouldRenderPane('charts')) {
      chartPane.classList.remove('scoring-chart-grid');
      if (hierarchyScoreTable) renderHierarchyCharts(chartPane, hierarchyScoreTable);
      else renderCharts(chartPane, chartRowsForEnvironment(payload.charts ?? [], allScoreTables, effectiveEnvironment), scoreTables);
    }
    if (shouldRenderPane('best-network')) renderBestNetworkChart(bestNetworkPane, scoreTables, hierarchyScoreTable);
    if (shouldRenderPane('gap')) {
      const gapTotals = normalizeRows(payload.gap_totals ?? []);
      if (displayHierarchyGapTable) {
        renderHierarchyGapViews(gapPane, displayHierarchyGapTable, displayHierarchyScoreTable);
      } else if (displayGapSummaryTables.length) {
        renderGapSummaryViews(gapPane, displayGapSummaryTables);
      } else if (hasGapViews) {
        renderGapViews(gapPane, displayGapTables);
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
    }
    const warnings = payload.warnings ?? job?.warnings ?? [];
    renderWarnings(warnings);
    const levels = jobLevels(job || payload.job || {}) || 'Operator';
    const mode = valueOf(job || payload.job, ['nr_mode'], 'All NR Modes');
    const baseline = valueOf(job || payload.job, ['baseline_operator'], 'EE');
    const profileName = valueOf(job || payload.job, ['scoring_profile_name', 'profile_name'], '');
    const fallbackMeta = environmentSelection.fallback
      ? ` (Combined view unavailable; showing ${environmentLabel(environmentSelection.fallback)} because required coverage is incomplete)` : '';
    const environmentMeta = selectedEnvironment ? ` · ${environmentLabel(selectedEnvironment)}${fallbackMeta}` : '';
    const profileMeta = profileName ? ` · Scoring methodology: ${profileName}` : '';
    resultMeta.textContent = `${formatDate(valueOf(job || payload.job, ['created_at', 'completed_at', 'submitted_at'], ''))} · ${levels} · ${mode}${environmentMeta}${profileMeta} · GAP: compared operator minus ${baseline} · Filters: ${contextFilterSummary(job || payload.job)}`;
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

  async function loadJob(job, force = false, updateJobList = true) {
    const id = jobIdOf(job);
    if (!id) return;
    selectedJobId = id;
    selectedJob = job;
    if (updateJobList) renderJobs();
    if (!force && resultCache.has(id) && isComplete(job)) {
      const cached = resultCache.get(id);
      if (currentResultsJobId !== id || currentResults !== cached) renderResult(cached, job);
      return;
    }
    if (currentResultsJobId !== id) {
      currentResults = null;
      currentResultsJobId = null;
      renderNoResult('Loading scoring results…');
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
        currentResults = null;
        currentResultsJobId = null;
        const error = valueOf(record, ['error', 'error_message', 'last_error'], 'This scoring job failed without an error message.');
        renderNoResult(error);
        resultMeta.textContent = `${jobSummary(record)} · Failed · ${error} · Filters: ${contextFilterSummary(record)}`;
      } else {
        currentResults = null;
        currentResultsJobId = null;
        renderNoResult('Scoring results will appear here when the job completes.');
        resultMeta.textContent = `${jobSummary(record)} · ${status} · ${jobLevels(record)} · Filters: ${contextFilterSummary(record)}`;
        setExportLinks('', false);
      }
    } catch (error) {
      if (deletedJobIds.has(id) || selectedJobId !== id) return;
      currentResults = null;
      currentResultsJobId = null;
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
        if (!hasCached || isActive(selectedJob)) await loadJob(selectedJob, isActive(selectedJob), false);
        else {
          const id = jobIdOf(selectedJob);
          const cached = resultCache.get(id);
          if (currentResultsJobId !== id || currentResults !== cached) renderResult(cached, selectedJob);
        }
      } else {
        currentResults = null;
        currentResultsJobId = null;
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
        currentResultsJobId = null;
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
    const levels = [...new Set(selectedLevels())];
    if (!levels.includes('Operator')) levels.unshift('Operator');
    const payload = {
      dataset_ids: datasetIds,
      aggregation_levels: levels,
      scoring_profile_id: scoringProfileSelect?.value || undefined,
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
    if (event.target === scoringProfileSelect) {
      const profile = scoringProfileById.get(scoringProfileSelect.value);
      if (profile && applyProfileHierarchy(profile.aggregation_hierarchy)) {
        setMessage(`This calculation will use ${profile.name}.`, 'success');
      }
      return;
    }
    if (event.target === environmentSelect && currentResults) {
      selectedEnvironment = environmentSelect.value;
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target === showKpiValuesToggle && currentResults) {
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target === tableModeSelect && currentResults) {
      renderResult(currentResults, selectedJob);
      setExportLinks(currentResultsJobId, true);
      return;
    }
    if (event.target === gapLayoutSelect && currentResults) {
      renderResult(currentResults, selectedJob);
      setExportLinks(currentResultsJobId, true);
      return;
    }
    const gapSummaryOperator = event.target.closest('[data-gap-summary-operator]');
    if (gapSummaryOperator && currentResults) {
      contextSelections.set(gapSummaryOperator.dataset.gapSummaryStateKey, gapSummaryOperator.value);
      renderResult(currentResults, selectedJob);
      return;
    }
    const hierarchyGapOperator = event.target.closest('[data-hierarchy-gap-operator]');
    if (hierarchyGapOperator && currentResults) {
      contextSelections.set(hierarchyGapOperator.dataset.hierarchyGapStateKey, hierarchyGapOperator.value);
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
    const tables = (Array.isArray(allTables) ? allTables : []).filter(table => environmentOf(table) === currentEffectiveEnvironment);
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
    if (activeResultTab === name) return;
    activeResultTab = name;
    for (const other of root.querySelectorAll('[data-result-tab]')) {
      const selected = other === tab;
      other.setAttribute('aria-selected', String(selected));
      other.tabIndex = selected ? 0 : -1;
    }
    for (const pane of root.querySelectorAll('[data-result-pane]')) pane.hidden = pane.dataset.resultPane !== name;
    if (currentResults) renderResult(currentResults, selectedJob, [name]);
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
