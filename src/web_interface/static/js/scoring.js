(() => {
  const root = document.querySelector('[data-scoring-workspace]');
  if (!root) return;

  const chartTooltip = document.createElement('div');
  chartTooltip.className = 'scoring-chart-tooltip';
  chartTooltip.id = 'scoring-chart-tooltip';
  chartTooltip.setAttribute('role', 'tooltip');
  chartTooltip.hidden = true;
  root.append(chartTooltip);
  let chartTooltipTarget = null;

  function chartTooltipAnchor(target) {
    const anchor = target?.closest?.('[data-chart-tooltip]')
      || target?.closest?.('[aria-label], [title]');
    return anchor && root.contains(anchor)
      && !anchor.matches('svg')
      && anchor.closest('.scoring-chart-svg') ? anchor : null;
  }

  function chartTooltipText(anchor) {
    return String(anchor?.getAttribute('data-chart-tooltip')
      || anchor?.getAttribute('aria-label')
      || anchor?.getAttribute('title')
      || anchor?.querySelector('title')?.textContent
      || '').trim();
  }

  function positionChartTooltip(event, anchor = chartTooltipTarget) {
    const text = chartTooltipText(anchor);
    if (!text) {
      chartTooltip.hidden = true;
      chartTooltipTarget = null;
      return;
    }
    chartTooltipTarget = anchor;
    chartTooltip.textContent = text;
    chartTooltip.hidden = false;
    const bounds = chartTooltip.getBoundingClientRect();
    const anchorBounds = anchor.getBoundingClientRect();
    const clientX = Number.isFinite(event?.clientX) ? event.clientX : anchorBounds.left + anchorBounds.width / 2;
    const clientY = Number.isFinite(event?.clientY) ? event.clientY : anchorBounds.top + anchorBounds.height / 2;
    const left = Math.max(8, Math.min(window.innerWidth - bounds.width - 8, clientX + 14));
    const top = Math.max(8, Math.min(window.innerHeight - bounds.height - 8, clientY + 14));
    chartTooltip.style.left = `${left}px`;
    chartTooltip.style.top = `${top}px`;
  }

  root.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    const anchor = chartTooltipAnchor(event.target);
    if (anchor) positionChartTooltip(event, anchor);
  });
  root.addEventListener('pointermove', event => {
    if (chartTooltipTarget && event.pointerType !== 'touch') positionChartTooltip(event);
  });
  root.addEventListener('pointerout', event => {
    if (!chartTooltipTarget) return;
    const nextAnchor = chartTooltipAnchor(event.relatedTarget);
    if (nextAnchor === chartTooltipTarget) return;
    chartTooltip.hidden = true;
    chartTooltipTarget = null;
  });
  root.addEventListener('focusin', event => {
    const anchor = chartTooltipAnchor(event.target);
    if (anchor) positionChartTooltip(null, anchor);
  });
  root.addEventListener('focusout', event => {
    if (chartTooltipTarget && !chartTooltipTarget.contains(event.relatedTarget)) {
      chartTooltip.hidden = true;
      chartTooltipTarget = null;
    }
  });

  const jobsUrl = root.dataset.jobsUrl || '/api/scoring/jobs';
  const selectionUrl = root.dataset.selectionUrl || '/api/scoring/selection';
  const exportBase = root.dataset.exportBase || '/scoring/jobs';
  const requestedJobId = new URLSearchParams(window.location.search).get('job_id');
  const requestedJobIdPending = {value: requestedJobId};
  const scoringViewStorageKey = [
    'dashboard-analytic', 'scoring-view',
    encodeURIComponent(document.body.dataset.authenticatedUser || 'anonymous'),
    encodeURIComponent(root.dataset.scoringWorkspaceId || 'unknown'),
  ].join(':');
  const resultTabNames = new Set(['scoring', 'gap', 'charts', 'best-network']);
  function readScoringViewState() {
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(scoringViewStorageKey) || 'null');
      if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};
      return {
        jobId: typeof stored.job_id === 'string' && stored.job_id ? stored.job_id : null,
        resultTab: resultTabNames.has(stored.result_tab) ? stored.result_tab : null,
        scrollY: Number.isFinite(stored.scroll_y) && stored.scroll_y >= 0 ? stored.scroll_y : null,
        environment: typeof stored.environment === 'string' && stored.environment ? stored.environment : 'all',
        showKpiValues: stored.show_kpi_values === true,
        showGapValues: stored.show_gap_values === true,
        gapLayout: ['end', 'adjacent'].includes(stored.gap_layout) ? stored.gap_layout : 'end',
      };
    } catch (_error) {
      return {};
    }
  }
  const restoredScoringViewState = readScoringViewState();
  let scoringViewScrollRestorePending = Number.isFinite(restoredScoringViewState.scrollY);
  let scoringViewScrollRestoreStarted = false;
  let scoringViewSaveTimer = null;
  function persistScoringViewState() {
    try {
      window.sessionStorage.setItem(scoringViewStorageKey, JSON.stringify({
        job_id: selectedJobId,
        result_tab: activeResultTab,
        scroll_y: window.scrollY,
        environment: selectedEnvironment,
        show_kpi_values: Boolean(showKpiValuesToggle?.checked),
        show_gap_values: showGapValues(),
        gap_layout: selectedGapLayout(),
      }));
    } catch (_error) {
      // View state is optional when browser session storage is unavailable.
    }
  }
  function restoreScoringViewScroll() {
    if (!scoringViewScrollRestorePending || scoringViewScrollRestoreStarted) return;
    scoringViewScrollRestoreStarted = true;
    scoringViewScrollRestorePending = false;
    const target = restoredScoringViewState.scrollY;
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      window.scrollTo({left: window.scrollX, top: Math.min(target, maximum), behavior: 'auto'});
      persistScoringViewState();
    }));
  }
  window.addEventListener('scroll', () => {
    if (scoringViewSaveTimer !== null) window.clearTimeout(scoringViewSaveTimer);
    scoringViewSaveTimer = window.setTimeout(() => {
      scoringViewSaveTimer = null;
      persistScoringViewState();
    }, 120);
  }, {passive: true});
  window.addEventListener('pagehide', persistScoringViewState);
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
  const calculationPanel = root.querySelector('.scoring-controls');
  const message = root.querySelector('[data-scoring-message]');
  const jobList = root.querySelector('[data-job-list]');
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
  const showGapValuesToggle = root.querySelector('[data-show-gap-values]');
  const gapLayoutSelect = root.querySelector('[data-scoring-gap-layout]');
  const gapLayoutControl = root.querySelector('[data-scoring-gap-layout-control]');
  if (showKpiValuesToggle) showKpiValuesToggle.checked = restoredScoringViewState.showKpiValues === true;
  if (showGapValuesToggle) showGapValuesToggle.checked = restoredScoringViewState.showGapValues === true;
  if (gapLayoutSelect) gapLayoutSelect.value = restoredScoringViewState.gapLayout || 'end';
  const resultPanes = [...root.querySelectorAll('[data-result-pane]')];
  const resultCache = new Map();
  const contextSelections = new Map();
  const scoringValueObservers = new Map();
  const deletedJobIds = new Set();
  const deletingJobIds = new Set();
  let jobs = [];
  let selectedJobId = restoredScoringViewState.jobId;
  let selectedJob = null;
  let selectedEnvironment = restoredScoringViewState.environment || 'all';
  let currentEffectiveEnvironment = null;
  let currentResults = null;
  let currentResultsJobId = null;
  let activeResultTab = restoredScoringViewState.resultTab
    || root.querySelector('[data-result-tab][aria-selected="true"]')?.dataset.resultTab || 'scoring';
  for (const tab of root.querySelectorAll('[data-result-tab]')) {
    const selected = tab.dataset.resultTab === activeResultTab;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
  for (const pane of resultPanes) pane.hidden = pane.dataset.resultPane !== activeResultTab;
  let chartFocusReturn = null;
  let previousBodyOverflow = '';
  let userSelectedJob = Boolean(selectedJobId);
  let refreshInFlight = false;
  let timer = null;
  let selectionLoaded = false;
  let selectionPersisted = false;
  let selectionDirty = false;
  let restoringSelection = false;
  let selectionSaveTimer = null;
  let selectionRevision = 0;
  let lastSavedSelectionKey = '';
  let lastQueuedSelectionKey = '';
  let selectionSaveChain = Promise.resolve();
  const selectionClientId = window.crypto?.randomUUID?.()
    || `scoring-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const selectionFieldOrder = ['Region', 'City', 'Operator', 'Vendor', 'Campaign'];

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
      const available = select ? [...select.options].filter(option => !option.disabled && option.value) : [];
      return [key, available.length && values.length === available.length ? [] : values];
    }));
  }

  function calculationSelectionFromControls() {
    const levels = [...new Set(selectedLevels())];
    if (!levels.includes('Operator')) levels.unshift('Operator');
    const filters = selectedContextFilters();
    return {
      dataset_ids: selectedDatasetIds().map(value => Number(value)).filter(Number.isFinite),
      aggregation_levels: levels,
      nr_mode: String(nrFilter?.value || 'NSA'),
      baseline_operator: String(baselineInput?.value || ''),
      scoring_profile_id: String(scoringProfileSelect?.value || activeProfileId),
      context_filters: Object.fromEntries(selectionFieldOrder.map(key => [key, filters[key] || []])),
    };
  }

  function calculationSelectionKey(selection) {
    const filters = selection?.context_filters && typeof selection.context_filters === 'object'
      ? selection.context_filters : {};
    const normalizedFilters = Object.fromEntries(selectionFieldOrder.map(key => [key,
      uniqueCatalogueValues(filters[key] ?? filters[key.toLowerCase()] ?? [])
        .sort((left, right) => left.localeCompare(right, undefined, {sensitivity: 'base'})),
    ]));
    return JSON.stringify({
      dataset_ids: (Array.isArray(selection?.dataset_ids) ? selection.dataset_ids : []).map(String).sort((left, right) => Number(left) - Number(right)),
      aggregation_levels: Array.isArray(selection?.aggregation_levels) ? selection.aggregation_levels.map(String) : [],
      nr_mode: String(selection?.nr_mode || ''),
      baseline_operator: String(selection?.baseline_operator || ''),
      scoring_profile_id: String(selection?.scoring_profile_id || ''),
      context_filters: normalizedFilters,
    });
  }

  function selectionWarnings(body) {
    const warnings = Array.isArray(body?.warnings) ? body.warnings.map(String).filter(Boolean) : [];
    if (warnings.length) setMessage(warnings.join(' '), 'warning');
  }

  function persistCalculationSelection({keepalive = false, force = false} = {}) {
    if (!selectionLoaded || restoringSelection) return Promise.resolve(null);
    const selection = calculationSelectionFromControls();
    const key = calculationSelectionKey(selection);
    if (!force && key === lastQueuedSelectionKey) return selectionSaveChain;
    lastQueuedSelectionKey = key;
    const clientRevision = ++selectionRevision;
    selectionSaveChain = selectionSaveChain.catch(() => null).then(async () => {
      const body = await requestJson(selectionUrl, {
        method: 'PUT',
        body: JSON.stringify({selection, client_id: selectionClientId, client_revision: clientRevision}),
        keepalive,
      });
      const savedSelection = body.selection || selection;
      const savedKey = calculationSelectionKey(savedSelection);
      if (lastQueuedSelectionKey === key) {
        if (savedKey !== key) {
          restoringSelection = true;
          applySavedCalculationSelection(savedSelection);
          restoringSelection = false;
        }
        lastSavedSelectionKey = savedKey;
        lastQueuedSelectionKey = savedKey;
        selectionPersisted = true;
        selectionDirty = calculationSelectionKey(calculationSelectionFromControls()) !== savedKey;
      }
      selectionWarnings(body);
      if (savedKey !== key && !(Array.isArray(body.warnings) && body.warnings.length)) {
        setMessage('Some scoring selection values were normalized by the workspace. Review the selected filters before calculating.', 'warning');
      }
      if (body.accepted === false && calculationSelectionKey(calculationSelectionFromControls()) !== savedKey) {
        scheduleSelectionSave();
      }
      return body;
    }).catch(error => {
      if (lastQueuedSelectionKey === key) lastQueuedSelectionKey = '';
      setMessage(`The latest scoring selection could not be saved: ${error.message}`, 'warning');
      return null;
    });
    return selectionSaveChain;
  }

  function scheduleSelectionSave() {
    if (!selectionLoaded || restoringSelection) return;
    selectionDirty = true;
    if (selectionSaveTimer !== null) window.clearTimeout(selectionSaveTimer);
    selectionSaveTimer = window.setTimeout(() => {
      selectionSaveTimer = null;
      persistCalculationSelection();
    }, 250);
  }

  function applySavedCalculationSelection(selection) {
    restoringSelection = true;
    try {
      const requestedMode = String(selection?.nr_mode || 'NSA');
      if ([...(nrFilter?.options || [])].some(option => option.value === requestedMode)) nrFilter.value = requestedMode;
      applyNrFilter(false);

      const datasetIds = new Set((Array.isArray(selection?.dataset_ids) ? selection.dataset_ids : []).map(String));
      for (const input of datasetInputs) {
        const option = input.closest('[data-dataset-option]');
        input.checked = datasetIds.has(String(input.value)) && !option?.hidden;
      }
      updateSelection();

      const profileId = String(selection?.scoring_profile_id || activeProfileId);
      const profile = scoringProfileById.get(profileId);
      if (profile) {
        scoringProfileSelect.value = profile.id;
        applyProfileHierarchy(profile.aggregation_hierarchy);
      }
      const levels = new Set((Array.isArray(selection?.aggregation_levels) ? selection.aggregation_levels : []).map(String));
      for (const input of aggregationInputs) input.checked = input.value === 'Operator' || levels.has(input.value);

      const baseline = String(selection?.baseline_operator || '');
      if (baseline && [...(baselineInput?.options || [])].some(option => option.value.toLocaleLowerCase() === baseline.toLocaleLowerCase())) {
        baselineInput.value = [...baselineInput.options].find(option => option.value.toLocaleLowerCase() === baseline.toLocaleLowerCase()).value;
      }

      updateSelection();
      const filters = selection?.context_filters && typeof selection.context_filters === 'object' ? selection.context_filters : {};
      const unavailableFilters = [];
      for (const key of selectionFieldOrder) {
        const select = contextFilterSelects.get(key);
        if (!select) continue;
        const requested = filters[key] ?? filters[key.toLowerCase()] ?? [];
        const requestedValues = uniqueCatalogueValues(Array.isArray(requested) ? requested : [requested]);
        const available = new Set([...select.options].filter(option => !option.disabled).map(option => option.value.toLocaleLowerCase()));
        const unavailable = requestedValues.filter(value => !available.has(value.toLocaleLowerCase()));
        if (unavailable.length) unavailableFilters.push(`${key}: ${unavailable.join(', ')}`);
        const selected = new Set(requestedValues.map(value => value.toLocaleLowerCase()));
        for (const option of select.options) option.selected = !option.disabled && selected.has(option.value.toLocaleLowerCase());
        select.dispatchEvent(new Event('change', {bubbles: true}));
      }
      updateSelection();
      if (unavailableFilters.length) {
        setMessage(`Some saved context filter values are no longer available: ${unavailableFilters.join(' · ')}. Review the selection before calculating.`, 'warning');
      }
    } finally {
      restoringSelection = false;
    }
  }

  async function loadCalculationSelection() {
    if (calculationPanel) {
      calculationPanel.inert = true;
      calculationPanel.setAttribute('aria-busy', 'true');
    }
    try {
      const body = await requestJson(selectionUrl);
      if (!body.selection || typeof body.selection !== 'object') throw new Error('The saved scoring selection is unavailable.');
      applySavedCalculationSelection(body.selection);
      const appliedKey = calculationSelectionKey(calculationSelectionFromControls());
      selectionPersisted = body.persisted !== false;
      lastSavedSelectionKey = selectionPersisted ? appliedKey : '';
      lastQueuedSelectionKey = selectionPersisted ? appliedKey : '';
      selectionLoaded = true;
      const initialWarnings = Array.isArray(body.warnings) ? body.warnings.map(String).filter(Boolean) : [];
      if (!selectionPersisted) {
        selectionDirty = true;
        await persistCalculationSelection({force: true});
      }
      selectionWarnings({warnings: initialWarnings});
    } catch (error) {
      applyNrFilter(true);
      selectionLoaded = true;
      selectionPersisted = false;
      selectionDirty = false;
      lastSavedSelectionKey = '';
      lastQueuedSelectionKey = '';
      setMessage(`Saved scoring selections could not be loaded. Current defaults are shown: ${error.message}`, 'warning');
    } finally {
      if (calculationPanel) {
        calculationPanel.inert = false;
        calculationPanel.removeAttribute('aria-busy');
      }
    }
  }

  function flushSelectionSaveOnPageHide() {
    if (selectionSaveTimer !== null) window.clearTimeout(selectionSaveTimer);
    selectionSaveTimer = null;
    if (!selectionLoaded || restoringSelection || !selectionDirty) return;
    const selection = calculationSelectionFromControls();
    const key = calculationSelectionKey(selection);
    if (selectionPersisted && key === lastSavedSelectionKey && key === lastQueuedSelectionKey) return;
    const clientRevision = ++selectionRevision;
    lastQueuedSelectionKey = key;
    fetch(selectionUrl, {
      method: 'PUT',
      credentials: 'same-origin',
      keepalive: true,
      headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
      body: JSON.stringify({selection, client_id: selectionClientId, client_revision: clientRevision}),
    }).catch(() => {});
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

  function jobCdrSummary(job) {
    let names = valueOf(job, ['dataset_names', 'cdr_names', 'source_names'], null);
    if (!Array.isArray(names) || !names.length) {
      const metadata = job?.source_metadata;
      const entries = Array.isArray(metadata) ? metadata : (metadata && typeof metadata === 'object' ? Object.values(metadata) : []);
      names = entries.map(entry => firstValue(entry, ['name', 'dataset_name', 'cdr_name'], '')).filter(Boolean);
    }
    if (Array.isArray(names) && names.length) return uniqueCatalogueValues(names).join(', ');
    const ids = valueOf(job, ['dataset_ids', 'cdr_ids'], []);
    const count = Array.isArray(ids) ? ids.length : Number(valueOf(job, ['dataset_count'], 0));
    return `${count || 'Selected'} CDR${count === 1 ? '' : 's'}`;
  }

  function savedJobFilterValues(job, key) {
    for (const filters of [job?.context_filters, job?.resolved_context_filters]) {
      if (!filters || typeof filters !== 'object') continue;
      const value = firstValue(filters, [key], null);
      if (value === null || value === undefined) continue;
      const values = uniqueCatalogueValues(Array.isArray(value) ? value : [value]);
      const datasetIds = valueOf(job, ['dataset_ids', 'cdr_ids'], []);
      const catalogueKey = catalogueKeyByLevel.get(key);
      if (values.length && Array.isArray(datasetIds) && datasetIds.length
          && datasetIds.every(id => Array.isArray(datasetCatalogues.get(String(id))?.[catalogueKey]))) {
        const available = new Set(datasetIds.flatMap(id => datasetCatalogues.get(String(id))[catalogueKey])
          .map(item => String(item).trim().toLocaleLowerCase()).filter(Boolean));
        const selected = new Set(values.map(item => item.toLocaleLowerCase()));
        if (available.size && available.size === selected.size && [...available].every(item => selected.has(item))) return [];
      }
      return values;
    }
    return [];
  }

  function jobCardTitleSegments(job) {
    const filterValue = (key, fallback) => savedJobFilterValues(job, key).join(', ') || fallback;
    const campaignFilter = savedJobFilterValues(job, 'Campaign');
    const campaigns = campaignFilter.length ? campaignFilter : jobCampaigns(job).filter(value => value !== 'Unspecified');
    const campaignValue = campaigns.length ? campaigns.join(', ') : 'All Campaigns';
    return [
      {dimension: 'neutral', value: formatDate(valueOf(job, ['created_at', 'submitted_at', 'started_at'], ''))},
      {dimension: 'nr-mode', value: valueOf(job, ['nr_mode'], 'All NR Modes')},
      {dimension: 'operator', value: filterValue('Operator', 'All Operators')},
      {dimension: 'vendor', value: filterValue('Vendor', 'All Vendors')},
      {dimension: 'region', value: filterValue('Region', 'All Regions')},
      {dimension: 'city', value: filterValue('City', 'All Cities')},
      {dimension: 'campaign', value: campaignValue},
    ];
  }

  function jobCardTitle(job) {
    return jobCardTitleSegments(job).map(segment => segment.value).join(' ● ');
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
      const titleSegments = jobCardTitleSegments(job);
      titleSegments.forEach((segment, index) => {
        if (index) {
          const separator = document.createElement('span');
          separator.className = 'scoring-job-title-separator';
          separator.dataset.dimension = 'neutral';
          separator.textContent = ' ● ';
          title.append(separator);
        }
        const value = document.createElement('span');
        value.className = `scoring-job-title-segment scoring-job-title-${segment.dimension}`;
        value.dataset.dimension = segment.dimension;
        value.textContent = segment.value;
        title.append(value);
      });
      title.setAttribute('aria-label', jobCardTitle(job));
      title.title = jobCardTitle(job);
      const statusBadge = document.createElement('span');
      statusBadge.className = 'scoring-status';
      statusBadge.dataset.status = status;
      statusBadge.textContent = status;
      top.append(title, statusBadge);
      button.append(top);
      const meta = document.createElement('span');
      meta.className = 'scoring-job-meta';
      const baseline = valueOf(job, ['baseline_operator'], 'EE');
      meta.textContent = `${jobLevels(job)} · GAP baseline ${baseline}`;
      button.append(meta);
      const cdrMeta = document.createElement('span');
      cdrMeta.className = 'scoring-job-meta';
      cdrMeta.textContent = `CDRs: ${jobCdrSummary(job)}`;
      button.append(cdrMeta);
      const profileName = valueOf(job, ['scoring_profile_name', 'profile_name'], '');
      if (profileName) {
        const profileMeta = document.createElement('span');
        profileMeta.className = 'scoring-job-meta';
        profileMeta.textContent = `Scoring methodology: ${profileName}`;
        button.append(profileMeta);
      }
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
    return 'expanded';
  }

  function selectedGapLayout() {
    return gapLayoutSelect?.value === 'adjacent' ? 'adjacent' : 'end';
  }

  function showGapValues() {
    return Boolean(showGapValuesToggle?.checked);
  }

  function syncGapValueControls() {
    if (gapLayoutControl) gapLayoutControl.hidden = !showGapValues();
  }

  function appendScoreGapCells(operators, nonBaseline, layout, appendScore, appendGap) {
    if (!showGapValues()) {
      for (const [operatorIndex, operator] of operators.entries()) appendScore(operator, operatorIndex);
      return;
    }
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
    return tableForMode(tableData, selectedTableMode());
  }

  function tableForMode(tableData, mode) {
    if (!tableData || typeof tableData !== 'object') return tableData;
    const rowsKey = mode === 'summary' ? 'category_rows' : 'expanded_rows';
    const totalKey = mode === 'summary' ? 'category_total' : 'expanded_total';
    if (!Array.isArray(tableData[rowsKey])) return tableData;
    const total = tableData[totalKey] && typeof tableData[totalKey] === 'object'
      ? tableData[totalKey] : tableData.total;
    return {
      ...tableData,
      _display_mode: mode,
      rows: tableData[rowsKey],
      total,
      ...(total && Object.hasOwn(total, 'gap_points') ? {total_gap_points: total.gap_points} : {}),
      ...(total && Object.hasOwn(total, 'gap_partial') ? {total_gap_partial: total.gap_partial} : {}),
      ...(total && Object.hasOwn(total, 'gap_environments') ? {total_gap_environments: total.gap_environments} : {}),
    };
  }

  function setExportLinks(jobId, enabled) {
    for (const [kind, selector] of [['scoring', '[data-export-scoring]'], ['gap', '[data-export-gap]'], ['ppt', '[data-export-ppt]']]) {
      const link = root.querySelector(selector);
      link.hidden = !enabled;
      const query = `table_mode=${encodeURIComponent(selectedTableMode())}&gap_layout=${encodeURIComponent(selectedGapLayout())}&environment=${encodeURIComponent(selectedEnvironment || 'all')}`;
      const gapOption = kind === 'ppt' ? `&show_gap_values=${showGapValues() ? 'true' : 'false'}` : '';
      link.href = enabled ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}?${query}${gapOption}` : '#';
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

  function renderTable(pane, source, emptyCopy, {hideGapColumns = false} = {}) {
    pane.replaceChildren();
    const rows = normalizeRows(source);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = emptyCopy;
      pane.append(empty);
      return;
    }
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))].filter(column => (
      !hideGapColumns || showGapValues() || !String(column).toLocaleLowerCase().includes('gap')
    ));
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-table-wrap';
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    for (const column of columns) {
      const th = document.createElement('th');
      th.scope = 'col';
      const isKpiType = ['kpi_type', 'type_of_kpi'].includes(String(column).toLocaleLowerCase());
      th.textContent = isKpiType ? 'Type of KPI' : humanizeKey(column);
      if (isKpiType) th.dataset.column = 'type';
      headerRow.append(th);
    }
    thead.append(headerRow);
    const tbody = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr');
      for (const column of columns) {
        const isKpiType = ['kpi_type', 'type_of_kpi'].includes(String(column).toLocaleLowerCase());
        if (isKpiType) {
          tr.append(createKpiTypeCell(row[column], ['category', 'total'].includes(String(row.row_type || '').toLocaleLowerCase())));
          continue;
        }
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
    if (Number.isFinite(numeric)) return numeric.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    return String(value);
  }

  function createKpiTypeCell(value, neutral = false) {
    const cell = document.createElement('td');
    cell.className = 'scoring-kpi-type-cell';
    cell.dataset.column = 'type';
    const rawType = String(value ?? '').trim();
    const normalized = rawType.toLocaleLowerCase();
    if (neutral) {
      cell.textContent = '—';
      cell.dataset.kpiType = 'neutral';
    } else if (normalized === 'reliable' || normalized === 'diff') {
      cell.textContent = rawType;
      cell.dataset.kpiType = normalized;
    } else {
      cell.textContent = rawType && normalized !== 'unknown' ? rawType : 'Not classified';
      cell.dataset.kpiType = 'neutral';
    }
    return cell;
  }

  function fitScoringValueCells(table) {
    if (!table?.isConnected) return;
    const measurement = document.createElement('canvas').getContext('2d');
    if (!measurement) return;
    for (const cell of table.querySelectorAll('tbody td[data-numeric="true"], tfoot td[data-numeric="true"]')) {
      cell.style.fontSize = '';
      const styles = window.getComputedStyle(cell);
      const fontSize = Number.parseFloat(styles.fontSize);
      const available = cell.clientWidth - Number.parseFloat(styles.paddingLeft) - Number.parseFloat(styles.paddingRight);
      if (!Number.isFinite(fontSize) || available <= 0) continue;
      measurement.font = styles.font;
      const contentWidth = measurement.measureText(cell.textContent.trim()).width;
      if (contentWidth <= 0 || available <= contentWidth * 1.05) continue;
      const scale = Math.min(1.65, available / (contentWidth * 1.05));
      cell.style.fontSize = `${Math.round(fontSize * scale * 10) / 10}px`;
    }
  }

  function observeScoringValueCells(table, wrapper) {
    if (typeof ResizeObserver !== 'function') {
      window.requestAnimationFrame(() => fitScoringValueCells(table));
      return;
    }
    const observer = new ResizeObserver(() => window.requestAnimationFrame(() => fitScoringValueCells(table)));
    scoringValueObservers.set(wrapper, observer);
    observer.observe(wrapper);
  }

  function disconnectScoringValueObservers(pane) {
    for (const [wrapper, observer] of scoringValueObservers) {
      if (!pane.contains(wrapper)) continue;
      observer.disconnect();
      scoringValueObservers.delete(wrapper);
    }
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
    if (!showGapValues()) return;
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

  function partialGapCoverage(partial, environments) {
    if (!partial) return '';
    const names = uniqueCatalogueValues(Array.isArray(environments) ? environments : []);
    return names.length
      ? `Partial GAP coverage: the arithmetic comparison is based only on ${names.join(', ')}.`
      : 'Partial GAP coverage: the arithmetic comparison uses only the available weighted environments.';
  }

  function addMatrixGapCell(row, value, color = '', partial = false, environments = []) {
    const td = document.createElement('td');
    td.dataset.numeric = 'true';
    td.dataset.column = 'gap';
    const numeric = value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
    td.textContent = `${formatMatrixNumber(value, true)}${partial && numeric ? '*' : ''}`;
    const safeColor = safeHexColor(color);
    if (safeColor) td.style.backgroundColor = safeColor;
    const partialNote = partialGapCoverage(partial, environments);
    if (partialNote) td.title = partialNote;
    if (numeric) {
      const numericValue = Number(value);
      const direction = numericValue > 0
        ? 'Positive GAP: the compared operator scores higher than the baseline for this KPI.'
        : numericValue < 0 ? 'Negative GAP: the compared operator scores lower than the baseline for this KPI.' : 'No GAP difference from the baseline.';
      td.title = [direction, partialNote].filter(Boolean).join(' ');
      if (numericValue > 0) {
        td.className = 'scoring-gap-gain';
      } else if (numericValue < 0) {
        td.className = 'scoring-gap-loss';
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
    const showGaps = showGapValues();
    const gapLayout = showGaps ? selectedGapLayout() : 'end';
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table';
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const title of ['Category', 'KPI', 'Type of KPI', 'Score weight (%)', 'Max score']) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.rowSpan = 2;
      th.dataset.column = ({Category: 'category', KPI: 'kpi', 'Type of KPI': 'type', 'Score weight (%)': 'weight', 'Max score': 'maximum'})[title];
      th.textContent = title;
      if (title === 'Score weight (%)') th.className = 'scoring-weight-header';
      if (title === 'Max score') th.className = 'scoring-maximum-header';
      header.append(th);
    }
    const showKpiValues = tableData?._display_mode !== 'summary' && Boolean(showKpiValuesToggle?.checked);
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
    } else if (showGaps && nonBaseline.length) {
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
        if (showGaps && nonBaseline.includes(operator)) appendGapHeader(operator);
      });
    } else {
      operators.forEach(appendScoreHeader);
      if (showGaps) nonBaseline.forEach(appendGapHeader);
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
      tr.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));

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
          const isCategoryRow = item?.row_type === 'category';
          const rawValue = !isCategoryRow && operatorCell && typeof operatorCell === 'object'
            ? firstValue(operatorCell, ['value', 'raw_value', 'kpi_value'], null) : null;
          const presentation = operatorPresentation(tableData, operator);
          const unit = firstValue(item, ['unit', 'units', 'measurement_unit'], '');
          cell.className = 'scoring-kpi-value-cell';
          cell.textContent = isCategoryRow ? '' : formatRawKpiValue(rawValue);
          cell.dataset.numeric = 'true';
          cell.title = isCategoryRow ? ''
            : `Raw ${item?.kpi || item?.kpi_code || 'KPI'} measurement for ${presentation.label}${unit ? ` (${unit})` : ''}: ${formatRawKpiValue(rawValue)}`;
          tr.append(cell);
        }
      }
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      const gapPartial = item?.gap_partial && typeof item.gap_partial === 'object' ? item.gap_partial : {};
      const gapEnvironments = item?.gap_environments && typeof item.gap_environments === 'object' ? item.gap_environments : {};
      appendScoreGapCells(operators, nonBaseline, gapLayout,
        (operator, operatorIndex) => addMatrixScoreCell(
          tr, operatorValue(values, operator), `scoring-tone-${operatorIndex % 5}`, item?.row_type === 'category',
        ),
        operator => addMatrixGapCell(tr, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''),
          firstValue(gapPartial, [operator], false), firstValue(gapEnvironments, [operator], [])),
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
      label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
      row.append(label);
      row.append(createKpiTypeCell('', true));
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
          cell.dataset.numeric = 'true';
          cell.textContent = 'N/A';
          cell.title = 'A single raw KPI measurement does not apply to the weighted total.';
          row.append(cell);
        });
      }
      const gaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
      const gapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      const gapPartial = total.gap_partial && typeof total.gap_partial === 'object' ? total.gap_partial : {};
      const gapEnvironments = total.gap_environments && typeof total.gap_environments === 'object' ? total.gap_environments : {};
      appendScoreGapCells(operators, nonBaseline, gapLayout,
        operator => addMatrixScoreCell(row, operatorValue(values, operator), '', true),
        operator => addMatrixGapCell(row, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''),
          firstValue(gapPartial, [operator], false), firstValue(gapEnvironments, [operator], [])),
      );
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
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
        setChartTooltip(label, firstColumn ? hierarchyPathFullLabel(firstColumn) : `${entry.level}: ${value}`);
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
          if (String(entry.level).toLocaleLowerCase() === 'operator') {
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
    const showKpiValues = tableData?._display_mode !== 'summary' && Boolean(showKpiValuesToggle?.checked);
    const showGaps = showGapValues();
    const gapLayout = showGaps ? selectedGapLayout() : 'end';
    const blocks = [
      ...(showKpiValues ? [{label: 'KPI Value', className: 'scoring-kpi-value-group', headerClass: 'scoring-kpi-value-header', column: 'kpi-value', columns: allColumns}] : []),
      ...(gapLayout === 'adjacent'
        ? allColumns.flatMap(column => [
          {label: 'Score', className: 'scoring-score-group', headerClass: 'scoring-score-header', column: 'score', columns: [column]},
          ...(showGaps && !hierarchyColumnIsReference(column)
            ? [{label: 'GAP', className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns: [column]}]
            : []),
        ])
        : [
          {label: 'Score', className: 'scoring-score-group', headerClass: 'scoring-score-header', column: 'score', columns: allColumns},
          ...(showGaps ? [{label: 'GAP', className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns: nonBaseline}] : []),
        ]),
    ];
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-hierarchy-table';
    const thead = document.createElement('thead');
    appendHierarchyHeaders(thead, tableData, allColumns, [
      ['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type'],
      ['Score weight (%)', 'weight', 'scoring-weight-header'], ['Max score', 'maximum', 'scoring-maximum-header'],
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
      row.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));
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
          const isCategoryRow = item?.row_type === 'category';
          const rawValue = !isCategoryRow && operatorCell && typeof operatorCell === 'object'
            ? firstValue(operatorCell, ['value', 'raw_value', 'kpi_value'], null) : null;
          const presentation = operatorPresentation(column.styleSource, column.id);
          const unit = firstValue(item, ['unit', 'units', 'measurement_unit'], '');
          cell.className = 'scoring-kpi-value-cell';
          cell.dataset.column = 'kpi-value';
          cell.textContent = isCategoryRow ? '' : formatRawKpiValue(rawValue);
          cell.dataset.numeric = 'true';
          cell.title = isCategoryRow ? ''
            : `Raw ${item?.kpi || item?.kpi_code || 'KPI'} measurement for ${presentation.label}${unit ? ` (${unit})` : ''}: ${formatRawKpiValue(rawValue)}`;
          row.append(cell);
        }
      }
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      const gapPartial = item?.gap_partial && typeof item.gap_partial === 'object' ? item.gap_partial : {};
      const gapEnvironments = item?.gap_environments && typeof item.gap_environments === 'object' ? item.gap_environments : {};
      appendScoreGapCells(allColumns, nonBaseline, gapLayout,
        (column, columnIndex) => addMatrixScoreCell(
          row, operatorValue(values, column.id), `scoring-tone-${columnIndex % 5}`, item?.row_type === 'category',
        ),
        column => addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], ''),
          firstValue(gapPartial, [column.id], false), firstValue(gapEnvironments, [column.id], [])),
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
      label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
      row.append(label);
      row.append(createKpiTypeCell('', true));
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
          cell.dataset.numeric = 'true';
          cell.textContent = 'N/A';
          cell.title = 'A single raw KPI measurement does not apply to the weighted total.';
          row.append(cell);
        });
      }
      const gaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
      const gapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
      const gapPartial = total.gap_partial && typeof total.gap_partial === 'object' ? total.gap_partial : {};
      const gapEnvironments = total.gap_environments && typeof total.gap_environments === 'object' ? total.gap_environments : {};
      appendScoreGapCells(allColumns, nonBaseline, gapLayout,
        column => addMatrixScoreCell(row, operatorValue(values, column.id), '', true),
        column => addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], ''),
          firstValue(gapPartial, [column.id], false), firstValue(gapEnvironments, [column.id], [])),
      );
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No KPI rows are available for this hierarchy.';
      pane.append(empty);
    }
  }

  function renderHierarchyScoringViews(pane, tableData, thresholdLegend = []) {
    disconnectScoringValueObservers(pane);
    pane.replaceChildren();
    if (!tableData) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No hierarchical scoring table is available for this environment.';
      pane.append(empty);
      return;
    }
    appendContextHeader(pane, tableData, 'score', 'Scoring Tables');
    appendThresholdLegend(pane, thresholdLegend.length ? thresholdLegend : tableData?.threshold_legend);
    appendScoringGapScale(pane, tableData);
    const summarySection = document.createElement('section');
    summarySection.className = 'scoring-table-mode-section';
    const summaryHeading = document.createElement('h4');
    summaryHeading.className = 'scoring-table-section-title';
    summaryHeading.textContent = 'Scoring Tables — Summary';
    summarySection.append(summaryHeading);
    appendHierarchyMatrixTable(summarySection, tableForMode(tableData, 'summary'));
    pane.append(summarySection);
    const expandedSection = document.createElement('section');
    expandedSection.className = 'scoring-table-mode-section';
    const expandedHeading = document.createElement('h4');
    expandedHeading.className = 'scoring-table-section-title';
    expandedHeading.textContent = 'Scoring Tables — Expanded';
    expandedSection.append(expandedHeading);
    appendHierarchyMatrixTable(expandedSection, tableForMode(tableData, 'expanded'));
    pane.append(expandedSection);
  }

  function renderHierarchyGapViews(pane, tableData, scoreTable) {
    disconnectScoringValueObservers(pane);
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
        categoryCell.className = 'scoring-category-cell';
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
      row.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));
      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      const gapPartial = item?.gap_partial && typeof item.gap_partial === 'object' ? item.gap_partial : {};
      const gapEnvironments = item?.gap_environments && typeof item.gap_environments === 'object' ? item.gap_environments : {};
      for (const column of columns) addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], ''),
        firstValue(gapPartial, [column.id], false), firstValue(gapEnvironments, [column.id], []));
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
      const totalGapPartial = total.gap_partial && typeof total.gap_partial === 'object' ? total.gap_partial : {};
      const totalGapEnvironments = total.gap_environments && typeof total.gap_environments === 'object' ? total.gap_environments : {};
      for (const column of columns) addMatrixGapCell(row, firstValue(totalGaps, [column.id], null), firstValue(totalGapColors, [column.id], ''),
        firstValue(totalGapPartial, [column.id], false), firstValue(totalGapEnvironments, [column.id], []));
      tfoot.append(row);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No KPI rows are available for this hierarchy comparison.';
      pane.append(empty);
    }
  }

  function renderScoringViews(pane, tables, thresholdLegend = []) {
    disconnectScoringValueObservers(pane);
    pane.replaceChildren();
    if (!tables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No scoring comparison tables are available for this job.';
      pane.append(empty);
      return;
    }
    const selected = appendComparisonSelector(pane, tables, 'score');
    appendContextHeader(pane, selected, 'score', 'Scoring Tables');
    appendThresholdLegend(pane, thresholdLegend.length ? thresholdLegend : selected?.threshold_legend);
    appendScoringGapScale(pane, selected);
    const summarySection = document.createElement('section');
    summarySection.className = 'scoring-table-mode-section';
    const summaryHeading = document.createElement('h4');
    summaryHeading.className = 'scoring-table-section-title';
    summaryHeading.textContent = 'Scoring Tables — Summary';
    summarySection.append(summaryHeading);
    appendMatrixTable(summarySection, tableForMode(selected, 'summary'));
    pane.append(summarySection);
    const expandedSection = document.createElement('section');
    expandedSection.className = 'scoring-table-mode-section';
    const expandedHeading = document.createElement('h4');
    expandedHeading.className = 'scoring-table-section-title';
    expandedHeading.textContent = 'Scoring Tables — Expanded';
    expandedSection.append(expandedHeading);
    appendMatrixTable(expandedSection, tableForMode(selected, 'expanded'));
    pane.append(expandedSection);
  }

  function renderGapViews(pane, tables) {
    disconnectScoringValueObservers(pane);
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
        if (key === 'type') {
          row.append(createKpiTypeCell(value, item?.row_type === 'category'));
          continue;
        }
        const cell = document.createElement('td');
        cell.dataset.column = key;
        if (key === 'gap') {
          cell.dataset.numeric = 'true';
          const partial = item?.gap_partial === true;
          const numericGap = value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
          cell.textContent = `${formatMatrixNumber(value, true)}${partial && numericGap ? '*' : ''}`;
          cell.title = [
            'Signed GAP: compared operator weighted points minus baseline weighted points. Positive means the compared operator leads.',
            partialGapCoverage(partial, item?.gap_environments),
          ].filter(Boolean).join(' ');
          const color = safeHexColor(item?.gap_color);
          if (color) cell.style.backgroundColor = color;
          if (Number(value) > 0) cell.classList.add('scoring-gap-gain');
          if (Number(value) < 0) cell.classList.add('scoring-gap-loss');
        } else {
          cell.textContent = value === null || value === undefined || value === '' ? 'N/A' : String(value);
          if (key === 'kpi') cell.title = String(item.kpi_code || item.kpi || '');
        }
        row.append(cell);
      }
      tbody.append(row);
    }
    table.append(thead, tbody);
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
    if (selected?.total_gap_points !== null && selected?.total_gap_points !== undefined) {
      const summary = document.createElement('p');
      summary.className = 'scoring-context-note';
      const label = selected.expanded_total?.gap_label || selected.total?.gap_label || 'Total signed GAP';
      const partial = selected.total_gap_partial === true;
      const partialNote = partialGapCoverage(partial, selected.total_gap_environments);
      summary.textContent = `${label} (${operator} − ${baseline}): ${formatMatrixNumber(selected.total_gap_points, true)}${partial ? '*' : ''} points.`;
      summary.title = partialNote;
      pane.append(summary);
    }
  }

  function renderGapSummaryViews(pane, tables) {
    disconnectScoringValueObservers(pane);
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
        categoryCell.className = 'scoring-category-cell';
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
      row.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));

      const gaps = item?.gaps && typeof item.gaps === 'object' ? item.gaps : {};
      const gapColors = item?.gap_colors && typeof item.gap_colors === 'object' ? item.gap_colors : {};
      const gapPartial = item?.gap_partial && typeof item.gap_partial === 'object' ? item.gap_partial : {};
      const gapEnvironments = item?.gap_environments && typeof item.gap_environments === 'object' ? item.gap_environments : {};
      for (const operator of comparisons) addMatrixGapCell(row, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''),
        firstValue(gapPartial, [operator], false), firstValue(gapEnvironments, [operator], []));
      tbody.append(row);
    }
    table.append(thead, tbody);

    const total = selected.total && typeof selected.total === 'object' ? selected.total : {};
    const totalGaps = total.gaps && typeof total.gaps === 'object' ? total.gaps : {};
    const totalGapColors = total.gap_colors && typeof total.gap_colors === 'object' ? total.gap_colors : {};
    const totalGapPartial = total.gap_partial && typeof total.gap_partial === 'object' ? total.gap_partial : {};
    const totalGapEnvironments = total.gap_environments && typeof total.gap_environments === 'object' ? total.gap_environments : {};
    if (Object.keys(totalGaps).length) {
      const tfoot = document.createElement('tfoot');
      const totalRow = document.createElement('tr');
      const labelCell = document.createElement('th');
      labelCell.scope = 'row';
      labelCell.colSpan = 3;
      labelCell.textContent = total.gap_label || 'Total signed GAP';
      totalRow.append(labelCell);
      for (const operator of comparisons) addMatrixGapCell(totalRow, firstValue(totalGaps, [operator], null), firstValue(totalGapColors, [operator], ''),
        firstValue(totalGapPartial, [operator], false), firstValue(totalGapEnvironments, [operator], []));
      tfoot.append(totalRow);
      table.append(tfoot);
    }
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
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

  function setChartTooltip(element, message, focusable = false) {
    const text = String(message || '').trim();
    if (!text) return element;
    element.setAttribute('data-chart-tooltip', text);
    element.setAttribute('aria-label', text);
    element.setAttribute('aria-describedby', chartTooltip.id);
    if (focusable) element.setAttribute('tabindex', '0');
    return element;
  }

  function formattedChartPoints(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toLocaleString(undefined, {maximumFractionDigits: 3}) : 'N/A';
  }

  function chartEnvironmentName(tableData) {
    const environment = String(tableData?.context?.environment || '');
    return environment ? environmentLabel(environment) : '';
  }

  function categoryLegendGray(index, count) {
    const channel = Math.round(58 + 168 * Math.max(0, index) / Math.max(1, count - 1));
    return `#${channel.toString(16).padStart(2, '0').repeat(3)}`;
  }

  let chartLegendMeasureContext = null;

  function chartLegendTextWidth(label) {
    try {
      if (!chartLegendMeasureContext) chartLegendMeasureContext = document.createElement('canvas').getContext('2d');
      if (chartLegendMeasureContext) {
        chartLegendMeasureContext.font = '750 15px "IBM Plex Sans", "Segoe UI", sans-serif';
        return chartLegendMeasureContext.measureText(label).width;
      }
    } catch (_error) {
      // Canvas measurement is optional in test and restricted browser contexts.
    }
    return label.length * 8;
  }

  function chartLegendRows(entries, width, left, right, fallbackColor) {
    const rows = [];
    for (const entry of entries) {
      const label = String(entry?.label || '');
      const entryWidth = 14 + 7 + chartLegendTextWidth(label) + 22;
      let row = rows[rows.length - 1];
      if (!row || (row.width + entryWidth > width - left - right && row.entries.length)) {
        row = {width: 0, entries: []};
        rows.push(row);
      }
      row.entries.push({...entry, label, entryWidth, color: safeHexColor(entry?.color) || fallbackColor});
      row.width += entryWidth;
    }
    return rows;
  }

  function categoryLegendTextLines(value, maxLength, maxLines = 2) {
    const lines = [];
    let current = '';
    for (let word of String(value).trim().split(/\s+/).filter(Boolean)) {
      while (word.length > maxLength) {
        if (current) {
          lines.push(current);
          current = '';
        }
        lines.push(word.slice(0, maxLength));
        word = word.slice(maxLength);
      }
      if (!word) continue;
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > maxLength && current) {
        lines.push(current);
        current = word;
      } else {
        current = candidate;
      }
    }
    if (current) lines.push(current);
    if (lines.length > maxLines) {
      const remainder = lines.slice(maxLines - 1).join(' ');
      lines.splice(maxLines - 1, lines.length - maxLines + 1,
        remainder.length > maxLength ? `${remainder.slice(0, maxLength - 1).trimEnd()}…` : remainder);
    }
    return lines;
  }

  function categoryLegendTextColor(background) {
    const color = safeHexColor(background);
    if (!color) return '#203744';
    const channels = [1, 3, 5].map(offset => Number.parseInt(color.slice(offset, offset + 2), 16) / 255);
    const linear = channels.map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    const luminance = .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
    const whiteContrast = 1.05 / (luminance + .05);
    const darkContrast = (luminance + .05) / .085;
    return darkContrast >= whiteContrast ? '#203744' : '#ffffff';
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
    const requestedChartWidth = Number(options.fitWidth);
    const width = Number.isFinite(requestedChartWidth) && requestedChartWidth > 0
      ? Math.max(720, Math.floor(requestedChartWidth))
      : Math.max(1180, categories.length * (stacked ? 150 : Math.max(168, series.length * 38 + 22)) + 150);
    const baseHeight = 700;
    const left = 86, right = 28, baseBottom = Math.max(150, 24 + (hasHierarchyAxis ? hierarchyLevels.length * 23 : 0));
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
    const legendRows = chartLegendRows(legendEntries, width, left, right, fallbackColors[0]);
    const categoryLegendEntries = Array.isArray(options.categoryLegendEntries) ? options.categoryLegendEntries : [];
    const categoryLegendHeight = categoryLegendEntries.length ? 76 : 0;
    const height = baseHeight + categoryLegendHeight;
    const top = Math.max(76, 42 + legendRows.length * 20);
    const chartHeight = baseHeight - top - baseBottom;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', title);

    legendRows.forEach((row, rowIndex) => {
      let x = left;
      for (const entry of row.entries) {
        const color = entry.color;
        const swatch = document.createElementNS(svg.namespaceURI, 'rect');
        swatch.setAttribute('x', String(x)); swatch.setAttribute('y', String(25 + rowIndex * 20)); swatch.setAttribute('width', '14'); swatch.setAttribute('height', '14');
        swatch.setAttribute('rx', '3'); swatch.setAttribute('fill', color);
        const legend = document.createElementNS(svg.namespaceURI, 'text');
        legend.setAttribute('x', String(x + 21)); legend.setAttribute('y', String(37 + rowIndex * 20));
        legend.setAttribute('class', 'scoring-chart-legend');
        legend.textContent = entry.label;
        setChartTooltip(swatch, String(entry.title || entry.label), true);
        setChartTooltip(legend, String(entry.title || entry.label), true);
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
          const hierarchyColumn = hierarchyColumnsById.get(String(category));
          const operatorName = hierarchyColumn
            ? String(hierarchyColumn.operator || firstValue(hierarchyColumn.styleSource, ['operator'], '') || '')
            : String(options.operatorForCategory?.(category) || '');
          const tooltipParts = [
            `KPI category: ${seriesName}`,
            hasHierarchyAxis ? `Hierarchy: ${fullCategory}` : `Category: ${fullCategory}`,
            operatorName ? `Operator: ${operatorPresentation(operatorTable, operatorName).label}` : '',
            chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
            `Weighted points: ${formattedChartPoints(numeric)}`,
            row.complete === false ? 'Coverage: incomplete' : '',
          ].filter(Boolean);
          setChartTooltip(rect, tooltipParts.join('\n'), true);
          svg.append(rect);
          if (segmentHeight >= 24) {
            const segmentLabel = document.createElementNS(svg.namespaceURI, 'text');
            segmentLabel.setAttribute('x', String(x + barWidth / 2));
            segmentLabel.setAttribute('y', String(segmentY + segmentHeight / 2 + 4));
            segmentLabel.setAttribute('text-anchor', 'middle');
            segmentLabel.setAttribute('class', 'scoring-best-network-segment');
            segmentLabel.textContent = numeric.toLocaleString(undefined, {maximumFractionDigits: 1});
            setChartTooltip(segmentLabel, tooltipParts.join('\n'));
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
          const hierarchyColumn = hierarchyColumnsById.get(String(category));
          const operatorName = hierarchyColumn
            ? String(hierarchyColumn.operator || '') : String(options.operatorForCategory?.(category) || '');
          setChartTooltip(unavailable, [
            'KPI categories total: unavailable because coverage is incomplete',
            options.categoryTooltips?.[category] ? `Hierarchy: ${options.categoryTooltips[category]}` : '',
            operatorName ? `Operator: ${operatorPresentation(operatorTable, operatorName).label}` : '',
            chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
          ].filter(Boolean).join('\n'), true);
          svg.append(unavailable);
        } else {
          const totalLabel = document.createElementNS(svg.namespaceURI, 'text');
          totalLabel.setAttribute('x', String(x + barWidth / 2));
          totalLabel.setAttribute('y', String(Math.max(top + 14, stackY - 7)));
          totalLabel.setAttribute('text-anchor', 'middle');
          totalLabel.setAttribute('class', 'scoring-chart-value');
          totalLabel.textContent = `${total.toLocaleString(undefined, {maximumFractionDigits: 1})}${complete ? '' : '*'}`;
          const hierarchyColumn = hierarchyColumnsById.get(String(category));
          const operatorName = hierarchyColumn
            ? String(hierarchyColumn.operator || firstValue(hierarchyColumn.styleSource, ['operator'], '') || '')
            : String(options.operatorForCategory?.(category) || '');
          setChartTooltip(totalLabel, [
            `KPI categories total: ${formattedChartPoints(total)}`,
            hasHierarchyAxis && options.categoryTooltips?.[category] ? `Hierarchy: ${options.categoryTooltips[category]}` : '',
            operatorName ? `Operator: ${operatorPresentation(operatorTable, operatorName).label}` : '',
            chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
            complete ? 'Coverage: complete' : 'Coverage: incomplete',
          ].filter(Boolean).join('\n'), true);
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
          const fullCategory = options.categoryTooltips?.[category] || options.categoryLabels?.[category] || category;
          setChartTooltip(unavailable, [
            `Category: ${fullCategory}`,
            options.seriesTooltips?.[seriesName] || `${mappedOrder.includes(seriesName) ? 'Operator' : 'Series'}: ${presentations.get(seriesName).label}`,
            chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
            'Weighted points: unavailable because coverage is incomplete',
          ].filter(Boolean).join('\n'), true);
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
        const fullCategory = options.categoryTooltips?.[category] || options.categoryLabels?.[category] || category;
        const isOperatorSeries = mappedOrder.includes(seriesName);
        const tooltipParts = [
          `Category: ${fullCategory}`,
          options.seriesTooltips?.[seriesName] || `${isOperatorSeries ? 'Operator' : 'Series'}: ${presentations.get(seriesName).label}`,
          chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
          `Weighted points: ${formattedChartPoints(row.value)}`,
          row.complete === false ? 'Coverage: incomplete' : '',
        ].filter(Boolean);
        setChartTooltip(rect, tooltipParts.join('\n'), true);
        const value = document.createElementNS(svg.namespaceURI, 'text');
        value.setAttribute('x', String(x + barWidth / 2));
        value.setAttribute('y', String(Math.max(top + 14, barTop - 7 - (seriesIndex % 2) * 22)));
        value.setAttribute('text-anchor', 'middle'); value.setAttribute('class', 'scoring-chart-value');
        value.textContent = `${Number.isInteger(row.value) ? row.value.toLocaleString() : row.value.toLocaleString(undefined, {maximumFractionDigits: 2})}${row.complete === false ? '*' : ''}`;
        setChartTooltip(value, tooltipParts.join('\n'));
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
        setChartTooltip(label, [
          `Category: ${fullCategory}`,
          chartEnvironmentName(operatorTable) ? `Environment: ${chartEnvironmentName(operatorTable)}` : '',
        ].filter(Boolean).join('\n'), true);
        svg.append(label);
      }
    });
    if (categoryLegendEntries.length) {
      svg.append(svgElement(svg, 'line', {
        x1: left, x2: width - right, y1: baseHeight + 3, y2: baseHeight + 3,
        stroke: '#d6dddf', 'stroke-width': 1,
      }));
      const legendTitle = svgElement(svg, 'text', {
        x: left, y: baseHeight + 17, class: 'scoring-chart-category-legend-title',
      });
      legendTitle.textContent = 'KPI categories';
      svg.append(legendTitle);
      const bandX = left;
      const bandY = baseHeight + 25;
      const bandWidth = width - left - right;
      const bandHeight = 40;
      const segmentWidth = bandWidth / categoryLegendEntries.length;
      categoryLegendEntries.forEach((entry, index) => {
        const x = bandX + segmentWidth * index;
        const fill = safeHexColor(entry?.color) || '#777777';
        const labelText = String(entry?.label || '');
        const tooltip = String(entry?.title || labelText);
        const segment = svgElement(svg, 'rect', {
          x, y: bandY, width: segmentWidth, height: bandHeight,
          fill, stroke: '#ffffff', 'stroke-width': 1,
          class: 'scoring-chart-category-legend-segment',
        });
        setChartTooltip(segment, tooltip, true);
        svg.append(segment);
        const fontSize = segmentWidth < 72 ? 10 : 12;
        const maxLength = Math.max(3, Math.floor((segmentWidth - 12) / (fontSize * .62)));
        const lines = categoryLegendTextLines(labelText, maxLength, 2);
        const label = svgElement(svg, 'text', {
          x: x + segmentWidth / 2,
          y: bandY + (bandHeight - lines.length * 14) / 2 + 11,
          'text-anchor': 'middle',
          class: 'scoring-chart-category-legend-label',
        });
        label.style.fontSize = `${fontSize}px`;
        label.style.fill = categoryLegendTextColor(fill);
        lines.forEach((line, lineIndex) => {
          const span = svgElement(svg, 'tspan', {
            x: x + segmentWidth / 2,
            dy: lineIndex ? 14 : 0,
          });
          span.textContent = line;
          label.append(span);
        });
        setChartTooltip(label, tooltip, true);
        svg.append(label);
      });
    }
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

  function chartOperatorLegend(operatorTable, operators) {
    const fallbackColors = ['#14867d', '#df7a45', '#5a82aa', '#8b63b1', '#b49a32'];
    const colors = new Map();
    const entries = operators.map((operator, index) => {
      const presentation = operatorPresentation(operatorTable, operator);
      const style = firstValue(operatorTable?.operator_styles || {}, [operator], {});
      const isReference = style?.is_reference === true || isReferenceOperator(operatorTable, operator);
      const color = presentation.color || fallbackColors[index % fallbackColors.length];
      colors.set(String(operator), color);
      return {
        label: `${presentation.label}${isReference ? ' (Reference)' : ''}`,
        color,
        title: `${presentation.label}${isReference ? ' is the reference operator.' : ''} Bar segments show KPI category shades; hover a bar for category and score details.`,
      };
    });
    return {colors, entries};
  }

  function chartCategoryLegend(categories, description = 'Grayscale key') {
    return categories.map((category, index) => ({
      label: category,
      color: categoryLegendGray(index, categories.length),
      title: `${category}. ${description} ${index + 1} identifies this KPI category.`,
    }));
  }

  function chartFitWidth(pane) {
    const width = Number(pane?.getBoundingClientRect?.().width || pane?.clientWidth || 0);
    return Number.isFinite(width) && width > 0 ? Math.max(720, width - 56) : null;
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
    appendContextHeader(pane, selected, 'score', 'Scoring Charts');
    const categories = [...new Set(selected.rows.map(row => String(row.category)))];
    const operators = Array.isArray(selected.operatorTable?.operators)
      ? selected.operatorTable.operators.map(String)
      : [...new Set(selected.rows.map(row => String(row.series)))];
    const {colors: operatorColors, entries: operatorLegend} = chartOperatorLegend(selected.operatorTable, operators);
    const categoryLegendEntries = chartCategoryLegend(categories);
    const operatorLabels = Object.fromEntries(operators.map(operator => [
      operator, operatorPresentation(selected.operatorTable, operator).label,
    ]));
    const stackedRows = selected.rows.map(row => ({
      ...row,
      category: String(row.series),
      series: String(row.category),
    }));
    const categorySeriesStyles = Object.fromEntries(categories.map(category => [category, {label: category}]));
    const stackedChart = makeSvgChart('Weighted score by operator', stackedRows, selected.operatorTable, {
      stacked: true,
      categoryOrder: operators,
      categoryLabels: operatorLabels,
      categoryTooltips: operatorLabels,
      seriesOrder: categories,
      seriesStyles: categorySeriesStyles,
      legendEntries: operatorLegend,
      categoryLegendEntries,
      operatorForCategory: operator => operator,
      segmentColor: (operator, _category, categoryIndex) => hierarchyChartColor(
        operatorColors.get(operator) || '#365F91', categoryIndex, categories.length,
      ),
    });
    stackedChart.style.minWidth = `${stackedChart.viewBox.baseVal.width}px`;
    pane.append(makeExpandableChartCard('Weighted score by operator', contextLabel(selected.context), stackedChart));
    const clusteredChart = makeSvgChart('Weighted score points by KPI category', selected.rows, selected.operatorTable, {
      legendEntries: operatorLegend,
      fitWidth: chartFitWidth(pane),
    });
    clusteredChart.style.minWidth = '0';
    clusteredChart.style.width = '100%';
    pane.append(makeExpandableChartCard(
      'Weighted score points by KPI category', contextLabel(selected.context), clusteredChart,
    ));
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
      const color = operatorColors.get(operator) || presentation.color
        || ['#14867d', '#df7a45', '#5a82aa', '#8b63b1'][operatorColors.size % 4];
      operatorColors.set(operator, color);
      if (seenOperators.has(operator)) continue;
      seenOperators.add(operator);
      operatorLegend.push({
        label: `${operator}${style.is_reference === true || column.is_reference === true ? ' (Reference)' : ''}`,
        color,
        title: `${operator}${style.is_reference === true || column.is_reference === true ? ' is the reference operator.' : ''} Segment shades identify KPI categories; hover a segment for its category and score.`,
      });
    }
    const categoryLegend = kpiCategories.map((category, index) => ({
      label: category,
      color: categoryLegendGray(index, kpiCategories.length),
      title: `${category}. Grayscale key ${index + 1} identifies this KPI category across operator-specific segment shades.`,
    }));
    const seriesStyles = Object.fromEntries(kpiCategories.map(category => [category, {label: category}]));
    appendContextHeader(pane, tableData, 'score', 'Scoring Charts');
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
      legendEntries: operatorLegend,
      categoryLegendEntries: categoryLegend,
      operatorForCategory: leafId => hierarchyColumnOperator(columns.find(column => column.id === leafId)),
      segmentColor: (leafId, _category, categoryIndex) => {
        const column = columns.find(item => item.id === leafId);
        const operator = String(column?.operator || firstValue(tableData?.operator_styles || {}, [leafId], {}).operator || '');
        return hierarchyChartColor(operatorColors.get(operator) || '#365F91', categoryIndex, kpiCategories.length);
      },
      axisLabel: 'Weighted score points',
    });
    chart.style.minWidth = `${chart.viewBox.baseVal.width}px`;
    pane.append(makeExpandableChartCard(
      'Weighted score by operator and aggregation', contextLabel(tableData.context), chart,
    ));
    const clusteredRows = sourceRows.map(row => ({
      category: String(row.category),
      series: String(row.operator),
      value: row.weighted_points,
      complete: row.complete,
    }));
    const clusteredSeriesStyles = {};
    const clusteredSeriesTooltips = {};
    const clusteredLegend = operatorLegend.map(entry => ({
      ...entry,
      title: `${entry.label} uses its mapped operator color; separate bars show hierarchy contexts.`,
    }));
    for (const column of columns) {
      const operator = hierarchyColumnOperator(column);
      const operatorLabel = operatorPresentation(tableData, operator).label;
      const isReference = hierarchyColumnIsReference(column);
      const pathLabel = hierarchyPathValueLabel(column) || operatorLabel;
      const pathTooltip = hierarchyPathFullLabel(column) || pathLabel;
      const color = operatorColors.get(operator) || '#365F91';
      clusteredSeriesStyles[column.id] = {label: pathLabel, color};
      clusteredSeriesTooltips[column.id] = `Operator: ${operatorLabel}${isReference ? ' (Reference)' : ''}\nHierarchy: ${pathTooltip}`;
    }
    const clusteredChart = makeSvgChart('Weighted score points by KPI category and operator context', clusteredRows, tableData, {
      categoryOrder: kpiCategories,
      seriesOrder: columns.map(column => column.id),
      seriesStyles: clusteredSeriesStyles,
      seriesTooltips: clusteredSeriesTooltips,
      legendEntries: clusteredLegend,
      fitWidth: chartFitWidth(pane),
    });
    clusteredChart.style.minWidth = '0';
    clusteredChart.style.width = '100%';
    pane.append(makeExpandableChartCard(
      'Weighted score points by KPI category and operator context', contextLabel(tableData.context), clusteredChart,
    ));
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
    const width = Math.max(980, data.operators.length * 85 + 128);
    const left = 92, right = 36;
    const fallbackColors = ['#14867d', '#df7a45', '#5a82aa', '#8b63b1'];
    const barColors = new Map(data.operators.map((operator, index) => {
      const mapped = operatorPresentation(tableData, operator);
      const hierarchyColumn = hierarchyColumnsById.get(operator);
      return [operator, {
        label: hierarchyColumn ? hierarchyPathValueLabel(hierarchyColumn) : mapped.label,
        fullLabel: hierarchyColumn ? hierarchyPathFullLabel(hierarchyColumn) : mapped.label,
        color: mapped.color || fallbackColors[index % fallbackColors.length],
      }];
    }));
    const legendByOperator = new Map();
    data.operators.forEach((operator, index) => {
      const column = hierarchyColumnsById.get(operator);
      const operatorName = hasHierarchyAxis ? hierarchyColumnOperator(column) : operator;
      if (!operatorName || legendByOperator.has(operatorName.toLocaleLowerCase())) return;
      const mapped = operatorPresentation(tableData, operatorName);
      const leafStyle = firstValue(tableData?.operator_styles || {}, [operator], {});
      const positionValue = mapped.position ?? Number(firstValue(leafStyle, ['position'], Number.NaN));
      const isReference = hierarchyColumnIsReference(column) || isReferenceOperator(tableData, operatorName);
      const label = `${mapped.label || barColors.get(operator)?.label || operatorName}${isReference ? ' (Reference)' : ''}`;
      legendByOperator.set(operatorName.toLocaleLowerCase(), {
        label,
        color: mapped.color || barColors.get(operator)?.color || fallbackColors[index % fallbackColors.length],
        title: `${hasHierarchyAxis ? `Operator: ${operatorName}` : `Operator: ${mapped.label || operatorName}`}${isReference ? ' (Reference)' : ''}. Data uses the mapped color; Voice uses a lighter tint.`,
        position: Number.isFinite(positionValue) ? positionValue : Number.POSITIVE_INFINITY,
        sourceIndex: index,
      });
    });
    const operatorLegendEntries = [...legendByOperator.values()].sort((leftEntry, rightEntry) => (
      leftEntry.position - rightEntry.position || leftEntry.sourceIndex - rightEntry.sourceIndex
    ));
    const operatorLegendRows = chartLegendRows(operatorLegendEntries, width, left, right, fallbackColors[0]);
    const baseHeight = 620;
    const top = Math.max(72, 45 + operatorLegendRows.length * 20);
    const height = baseHeight + Math.max(0, top - 72);
    const groupKeys = data.operators.map(operator => hierarchyColumnOperator(hierarchyColumnsById.get(operator)));
    const groupTransitions = hasHierarchyAxis
      ? groupKeys.slice(1).filter((key, index) => key && groupKeys[index] && key !== groupKeys[index]).length : 0;
    const categoryGroupGap = hasHierarchyAxis ? 14 : 0;
    const bottom = Math.max(124, 32 + (hasHierarchyAxis ? hierarchyLevels.length * 23 : 0));
    const plotHeight = baseHeight - 72 - bottom;
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
    const visibleWidth = data.operators.length > 10
      ? categoryStarts.get(data.operators[10]) + right : width;
    svg.style.width = `${100 * width / visibleWidth}%`;
    svg.style.minWidth = '0';
    svg.style.maxWidth = 'none';
    svg.style.minHeight = '0';
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Voice and Data weighted points by operator');
    if (operatorLegendRows.length) {
      const legendTitle = svgElement(svg, 'text', {x: left, y: 13, class: 'scoring-chart-operator-legend-title'});
      legendTitle.textContent = 'Operators';
      svg.append(legendTitle);
      operatorLegendRows.forEach((row, rowIndex) => {
        let x = left;
        for (const entry of row.entries) {
          const y = 23 + rowIndex * 20;
          const swatch = svgElement(svg, 'rect', {x, y, width: 14, height: 14, rx: 3, fill: entry.color});
          const label = svgElement(svg, 'text', {x: x + 21, y: y + 12, class: 'scoring-chart-legend'});
          label.textContent = entry.label;
          setChartTooltip(swatch, String(entry.title || entry.label), true);
          setChartTooltip(label, String(entry.title || entry.label), true);
          svg.append(swatch, label);
          x += entry.entryWidth;
        }
      });
    }
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
        const hierarchyText = hasHierarchyAxis ? `Hierarchy: ${presentation.fullLabel}` : `Operator: ${presentation.fullLabel}`;
        const segmentTooltip = [
          hierarchyText,
          `Series: ${kind}`,
          chartEnvironmentName(tableData) ? `Environment: ${chartEnvironmentName(tableData)}` : '',
          `Weighted points: ${formattedChartPoints(cell.value)}`,
          cell.complete ? 'Coverage: complete' : 'Coverage: incomplete',
        ].filter(Boolean).join('\n');
        setChartTooltip(rect, segmentTooltip, true);
        svg.append(rect);
        const segmentLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: segmentY + Math.max(13, segmentHeight / 2 + 4), 'text-anchor': 'middle', class: 'scoring-best-network-segment'});
        segmentLabel.textContent = `${kind === 'Data' ? 'D' : 'V'} ${cell.value.toLocaleString(undefined, {maximumFractionDigits: 1})}${cell.complete ? '' : '*'}`;
        const labelColor = readableTextColor(color) || '#17303c';
        segmentLabel.style.fill = labelColor;
        segmentLabel.style.stroke = labelColor === '#ffffff' ? 'rgba(0,0,0,.62)' : 'rgba(255,255,255,.88)';
        setChartTooltip(segmentLabel, segmentTooltip);
        svg.append(segmentLabel);
        stackY = segmentY;
      }
      const totalLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: Math.max(top + 18, stackY - 10), 'text-anchor': 'middle', class: 'scoring-chart-value'});
      totalLabel.textContent = hasPoints ? `${totalPoints.toLocaleString(undefined, {maximumFractionDigits: 1})}${complete ? '' : '*'}` : 'N/A';
      setChartTooltip(totalLabel, [
        hasHierarchyAxis ? `Hierarchy: ${presentation.fullLabel}` : `Operator: ${presentation.fullLabel}`,
        'Voice and Data total',
        chartEnvironmentName(tableData) ? `Environment: ${chartEnvironmentName(tableData)}` : '',
        `Weighted points: ${hasPoints ? formattedChartPoints(totalPoints) : 'unavailable'}`,
        complete ? 'Coverage: complete' : 'Coverage: incomplete; displayed points are not renormalized',
      ].filter(Boolean).join('\n'), true);
      svg.append(totalLabel);
      if (!hasHierarchyAxis) {
        const operatorLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: baselineY + 28, 'text-anchor': 'middle', class: 'scoring-chart-category'});
        const labelLines = wrappedSvgLabelLines(presentation.label, 24, 1);
        labelLines.forEach((line, lineIndex) => {
          const span = svgElement(svg, 'tspan', {x: x + barWidth / 2, dy: lineIndex ? '1.15em' : '0'});
          span.textContent = line;
          operatorLabel.append(span);
        });
        setChartTooltip(operatorLabel, [
          `Operator: ${presentation.fullLabel}`,
          chartEnvironmentName(tableData) ? `Environment: ${chartEnvironmentName(tableData)}` : '',
        ].filter(Boolean).join('\n'));
        svg.append(operatorLabel);
      }
    });
    return svg;
  }

  function maximumAllocationEnvironments(tableData, allTables, configuration = {}) {
    const requested = String(tableData?.context?.environment || 'Combined');
    const combined = ['combined', 'all', 'all environments'].includes(requested.toLowerCase());
    const environments = new Map();
    const configured = configuration?.scope?.environments || {};
    for (const [name, details] of Object.entries(configured)) {
      if (!(Number(details?.total_points) > 0)) continue;
      const allocation = {Voice: 0, Data: 0};
      for (const metric of configuration.metrics || []) {
        const points = Number(metric?.contexts?.[name]?.max_points);
        if (!Number.isFinite(points) || points <= 0) continue;
        const kind = String(metric.source_kind || metric.calculation?.source_kind || '').toLowerCase();
        if (['voice', 'speech'].includes(kind)) allocation.Voice += points;
        else if (kind === 'data') allocation.Data += points;
      }
      environments.set(name, {name, ...allocation});
    }
    if (!environments.size) {
      for (const table of allTables || []) {
        const name = String(table?.context?.environment || '');
        if (!name || ['combined', 'all', 'all environments'].includes(name.toLowerCase()) || environments.has(name)) continue;
        environments.set(name, {name, ...bestNetworkTotals(table).allocation});
      }
    }
    const palette = ['#4472C4', '#7030A0', '#C55A11', '#5B9BD5', '#A64D79'];
    const allocations = [...environments.values()].map((item, index) => ({...item, color: palette[index % palette.length]}))
      .filter(item => combined || item.name.toLowerCase() === requested.toLowerCase());
    return allocations.length ? allocations : [{name: requested, ...bestNetworkTotals(tableData).allocation, color: palette[0]}];
  }

  function allocationIconPath(kind) {
    if (kind === 'Voice') return 'M6 3h4l2 5-3 2c2 4 3 5 7 7l2-3 5 2v4c-1 3-5 2-8 0C7 16 2 7 6 3Z';
    if (kind === 'Data') return 'M7 3h10v18H7ZM10 7h10m-3-3 3 3-3 3M14 16H4m3-3-3 3 3 3';
    if (/city/i.test(kind)) return 'M3 21V7h7v14M10 21V3h10v18M1 21h22M6 10v2m0 3v2m8-10h3m-3 4h3m-3 4h3';
    if (/road/i.test(kind)) return 'M5 21 9 3m10 18L15 3M12 3v3m0 3v3m0 3v3m0 2v1';
    return 'M12 22s8-8 8-13a8 8 0 0 0-16 0c0 5 8 13 8 13ZM12 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z';
  }

  function makeMaximumAllocationDonut(environments) {
    const voiceColor = '#176E77';
    const dataColor = '#E6A81D';
    const combined = environments.length > 1;
    const total = environments.reduce((sum, item) => sum + item.Voice + item.Data, 0);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const legendHeight = 55 + environments.length * 86;
    const height = Math.max(320, legendHeight);
    svg.setAttribute('viewBox', `0 0 640 ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg scoring-allocation-donut');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Maximum score allocation by environment, Voice and Data');
    const cx = 155;
    const cy = height / 2;
    const ringCount = environments.length + (combined ? 1 : 0);
    const outerRadius = 126;
    const thickness = Math.min(32, 74 / ringCount);
    const ringGap = Math.min(2, 8 / ringCount);
    const rings = combined ? [{name: 'Global', segments: environments.map(item => ({label: item.name, value: item.Voice + item.Data, color: item.color}))}] : [];
    environments.forEach(item => rings.push({name: item.name, segments: [
      {label: 'Voice', value: item.Voice, color: voiceColor},
      {label: 'Data', value: item.Data, color: dataColor},
    ]}));
    rings.forEach((ring, index) => {
      const radius = outerRadius - index * (thickness + ringGap);
      const circumference = 2 * Math.PI * radius;
      const ringTotal = ring.segments.reduce((sum, segment) => sum + segment.value, 0);
      let offset = 0;
      ring.segments.forEach(segment => {
        const length = ringTotal > 0 ? circumference * segment.value / ringTotal : 0;
        const mark = svgElement(svg, 'circle', {cx, cy, r: radius, fill: 'none', stroke: segment.color,
          'stroke-width': thickness, 'stroke-dasharray': `${length} ${circumference - length}`,
          'stroke-dashoffset': -offset, transform: `rotate(-90 ${cx} ${cy})`});
        setChartTooltip(mark, `${ring.name}: ${segment.label}\nMaximum points: ${formattedChartPoints(segment.value)}\nShare of configured maximum: ${(ringTotal > 0 ? segment.value / ringTotal * 100 : 0).toFixed(1)}%`, true);
        svg.append(mark);
        offset += length;
      });
    });
    const center = svgElement(svg, 'text', {x: cx, y: cy - 4, 'text-anchor': 'middle', class: 'scoring-allocation-total'});
    center.textContent = total.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const innerRadius = outerRadius - (ringCount - 1) * (thickness + ringGap) - thickness / 2;
    center.setAttribute('style', `font-size:${Math.min(25, (innerRadius * 2 - 12) / (center.textContent.length * .65))}px`);
    const unit = svgElement(svg, 'text', {x: cx, y: cy + 20, 'text-anchor': 'middle', class: 'scoring-allocation-unit'});
    unit.textContent = 'max points';
    setChartTooltip(center, `Total configured maximum\nMaximum points: ${formattedChartPoints(total)}`);
    svg.append(center, unit);
    const legend = (label, color, value, y, iconKind, bold = false) => {
      const icon = svgElement(svg, 'path', {d: allocationIconPath(iconKind), fill: 'none', stroke: color,
        'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', transform: `translate(310 ${y - 17}) scale(.8)`});
      const swatch = svgElement(svg, 'rect', {x: 335, y: y - 12, width: 12, height: 12, rx: 2, fill: color});
      const text = svgElement(svg, 'text', {x: 354, y, fill: '#243746', 'font-size': 14, 'font-weight': bold ? 700 : 400});
      text.textContent = `${label}: ${formattedChartPoints(value)} pts`;
      setChartTooltip(text, text.textContent);
      svg.append(icon, swatch, text);
    };
    if (combined) legend('Global', '#465565', total, 30, 'Global', true);
    environments.forEach((item, index) => {
      const y = (combined ? 64 : 44) + index * 86;
      legend(item.name, item.color, item.Voice + item.Data, y, item.name, true);
      legend('Voice', voiceColor, item.Voice, y + 24, 'Voice');
      legend('Data', dataColor, item.Data, y + 48, 'Data');
    });
    return svg;
  }

  function renderBestNetworkChart(pane, scoreTables, hierarchyTable = null, allTables = scoreTables) {
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
    const configuration = selectedJob?.configuration || currentResults?.configuration || {};
    const allocations = maximumAllocationEnvironments(selected, allTables, configuration);
    const donut = makeMaximumAllocationDonut(allocations);
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
    const legacyCampaignNotice = 'Campaigns are scored separately; the supplied Tableau Prep flow pools campaigns.';
    const visibleItems = items.filter(warning => (
      (typeof warning === 'string' ? warning : displayValue(warning)) !== legacyCampaignNotice
    ));
    list.replaceChildren();
    box.hidden = !visibleItems.length;
    for (const warning of visibleItems) {
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
    const available = new Set();
    for (const table of tables) {
      const environment = environmentOf(table);
      if (!environment || environment === 'Combined') continue;
      available.add(environment);
    }
    const combinedIsAvailable = tables.some(table => environmentOf(table) === 'Combined');
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
      return {environments, effective: null, unavailable: false};
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
    const combinedIsAvailable = tables.some(table => environmentOf(table) === 'Combined');
    const effective = selectedEnvironment === 'all'
      ? (combinedIsAvailable ? 'Combined' : null)
      : selectedEnvironment;
    currentEffectiveEnvironment = effective;
    return {environments, effective, unavailable: selectedEnvironment === 'all' && !combinedIsAvailable};
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
        summaryHeading.textContent = 'Scoring Tables — Summary';
        const summaryTable = document.createElement('div');
        summaryTable.className = 'scoring-table-section';
        renderTable(summaryTable, totalsRows, 'No scoring summary rows are available.', {hideGapColumns: true});
        scoringPane.append(summaryHeading, summaryTable);
        const detailHeading = document.createElement('h4');
        detailHeading.className = 'scoring-table-section-title';
        detailHeading.textContent = 'Scoring Tables — Expanded';
        const detailTable = document.createElement('div');
        detailTable.className = 'scoring-table-section';
        renderTable(detailTable, detailRows, 'No KPI detail rows are available.', {hideGapColumns: true});
        scoringPane.append(detailHeading, detailTable);
      } else {
        scoringPane.replaceChildren();
        renderTable(scoringPane, detailRows, 'This job has no scoring table rows.', {hideGapColumns: true});
      }
    }
    if (shouldRenderPane('charts')) {
      chartPane.classList.remove('scoring-chart-grid');
      if (hierarchyScoreTable) renderHierarchyCharts(chartPane, hierarchyScoreTable);
      else renderCharts(chartPane, chartRowsForEnvironment(payload.charts ?? [], allScoreTables, effectiveEnvironment), scoreTables);
    }
    if (shouldRenderPane('best-network')) renderBestNetworkChart(bestNetworkPane, scoreTables, hierarchyScoreTable, allScoreTables);
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
    setExportLinks(jobIdOf(job || payload.job || {}), true);
  }

  function renderNoResult(text) {
    for (const pane of resultPanes) {
      disconnectScoringValueObservers(pane);
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
      } else {
        currentResults = null;
        currentResultsJobId = null;
        renderNoResult('Scoring results will appear here when the job completes.');
        setExportLinks('', false);
      }
    } catch (error) {
      if (deletedJobIds.has(id) || selectedJobId !== id) return;
      currentResults = null;
      currentResultsJobId = null;
      renderNoResult(error.message || 'The selected job could not be loaded.');
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
      const requested = requestedJobIdPending.value
        ? ordered.find(job => jobIdOf(job) === requestedJobIdPending.value) : null;
      requestedJobIdPending.value = null;
      const retained = !requested && userSelectedJob && selectedJobId
        ? ordered.find(job => jobIdOf(job) === selectedJobId) : null;
      selectedJob = requested || retained || ordered.find(isComplete) || ordered[0] || null;
      selectedJobId = selectedJob ? jobIdOf(selectedJob) : null;
      userSelectedJob = Boolean(requested || retained);
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
      if (scoringViewScrollRestorePending) restoreScoringViewScroll();
      else persistScoringViewState();
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
      await persistCalculationSelection();
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

  datasetInputs.forEach(input => input.addEventListener('change', () => {
    updateSelection();
    scheduleSelectionSave();
  }));
  nrFilter.addEventListener('change', () => {
    applyNrFilter(true);
    scheduleSelectionSave();
  });
  root.addEventListener('change', event => {
    if ([environmentSelect, showKpiValuesToggle, showGapValuesToggle, gapLayoutSelect].includes(event.target)) {
      if (event.target === environmentSelect) selectedEnvironment = environmentSelect.value;
      persistScoringViewState();
    }
    if (event.target === scoringProfileSelect) {
      const profile = scoringProfileById.get(scoringProfileSelect.value);
      if (profile && applyProfileHierarchy(profile.aggregation_hierarchy)) {
        setMessage(`This calculation will use ${profile.name}.`, 'success');
        scheduleSelectionSave();
      }
      return;
    }
    if (event.target === baselineInput || event.target.matches('[data-aggregation-level], [data-scoring-context-filter]')) {
      scheduleSelectionSave();
      return;
    }
    if (event.target === environmentSelect && currentResults) {
      selectedEnvironment = environmentSelect.value;
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target === showGapValuesToggle) {
      syncGapValueControls();
      if (currentResults) renderResult(currentResults, selectedJob, ['scoring']);
      return;
    }
    if (event.target === showKpiValuesToggle && currentResults) {
      renderResult(currentResults, selectedJob);
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
  jobList.addEventListener('click', async event => {
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
    persistScoringViewState();
    await loadJob(job, true);
    if (selectedJobId === jobIdOf(job)) {
      root.querySelector('.scoring-results-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
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
    persistScoringViewState();
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
  window.addEventListener('pagehide', flushSelectionSaveOnPageHide);
  syncGapValueControls();
  applyNrFilter(false);
  loadCalculationSelection();
  refreshJobs();
})();
