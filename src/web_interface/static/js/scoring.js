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
    'drivetest-analyzer', 'scoring-view',
    encodeURIComponent(document.body.dataset.authenticatedUser || 'anonymous'),
    encodeURIComponent(root.dataset.scoringWorkspaceId || 'unknown'),
  ].join(':');
  const resultTabNames = new Set(['scoring', 'gap', 'charts']);
  function readScoringViewState() {
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(scoringViewStorageKey) || 'null');
      if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};
      return {
        jobId: typeof stored.job_id === 'string' && stored.job_id ? stored.job_id : null,
        resultTab: stored.result_tab === 'best-network' ? 'charts'
          : resultTabNames.has(stored.result_tab) ? stored.result_tab : null,
        scrollY: Number.isFinite(stored.scroll_y) && stored.scroll_y >= 0 ? stored.scroll_y : null,
        environment: typeof stored.environment === 'string' && stored.environment ? stored.environment : 'all',
        scoring: stored.scoring === 'most_reliable' ? 'most_reliable' : 'best_network',
        showKpiValues: stored.show_kpi_values === true,
        showGapValues: stored.show_gap_values === true,
        gapLayout: ['end', 'adjacent'].includes(stored.gap_layout) ? stored.gap_layout : 'end',
        gapComparisons: stored.gap_comparisons && typeof stored.gap_comparisons === 'object'
          && !Array.isArray(stored.gap_comparisons)
          ? Object.fromEntries(Object.entries(stored.gap_comparisons).filter(([, value]) => (
            value === 'all' || (typeof value === 'string' && value.startsWith('operator:')
              && value.length > 'operator:'.length)
          ))) : {},
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
        scoring: typeof selectedScoring === 'undefined' ? 'best_network' : selectedScoring,
        show_kpi_values: Boolean(showKpiValuesToggle?.checked),
        show_gap_values: showGapValues(),
        gap_layout: selectedGapLayout(),
        gap_comparisons: typeof gapComparisonSelections === 'undefined'
          ? {} : Object.fromEntries(gapComparisonSelections),
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
  const defaultHierarchy = ['Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign'];
  const catalogueKeyByLevel = new Map([
    ['Operator', 'operators'], ['Vendor', 'vendors'], ['Region', 'regions'], ['Cluster', 'clusters'],
    ['City', 'cities'], ['Campaign', 'campaigns'],
  ]);
  // Hierarchies saved before Cluster existed get it right after Region.
  const completeHierarchy = hierarchy => (hierarchy.includes('Cluster') ? hierarchy
    : hierarchy.flatMap(level => (level === 'Region' ? ['Region', 'Cluster'] : [level])));
  const validHierarchy = hierarchy => {
    const levels = Array.isArray(hierarchy) ? completeHierarchy(hierarchy.map(String)) : [];
    return levels.length === defaultHierarchy.length && new Set(levels).size === defaultHierarchy.length
      && levels.every(level => catalogueKeyByLevel.has(level)) ? levels : null;
  };
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
  // Operator_Vendor and Vendor_Operator precede Vendor; they filter but are not aggregation levels.
  const filterCatalogueKeys = new Map([...catalogueKeyByLevel, ['Operator_Vendor', 'operator_vendors'], ['Vendor_Operator', 'vendor_operators']]);
  const contextFilterKeys = hierarchy => hierarchy.flatMap(key => (key === 'Vendor' ? ['Operator_Vendor', 'Vendor_Operator', 'Vendor'] : [key]));
  let contextFilterDefinitions = contextFilterKeys(currentHierarchy)
    .map(key => ({key, catalogueKey: filterCatalogueKeys.get(key)}));
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
  const jobLists = [...root.querySelectorAll('[data-job-list]')];
  const jobList = jobLists[0];
  const jobSelector = root.querySelector('[data-scoring-job-selector]');
  const selectedJobCard = root.querySelector('[data-selected-job-card]');
  const environmentControl = root.querySelector('[data-result-environment-control]');
  const environmentSelect = root.querySelector('[data-result-environment]');
  const scoringKindControl = root.querySelector('[data-result-scoring-control]');
  const scoringKindSelect = root.querySelector('[data-result-scoring]');
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
  const gapComparisonSelections = new Map(Object.entries(restoredScoringViewState.gapComparisons || {}));
  const scoringValueObservers = new Map();
  const deletedJobIds = new Set();
  const deletingJobIds = new Set();
  let jobs = [];
  let calculationMatchKey = '';
  let calculationMatchRevision = 0;
  let calculationMatchTimer = null;
  let submittingCalculation = false;
  let selectedJobId = restoredScoringViewState.jobId;
  let selectedJob = null;
  let selectedEnvironment = restoredScoringViewState.environment || 'all';
  // Best Network or Most Reliable: both scorings share the job, its filters and its aggregation.
  let selectedScoring = restoredScoringViewState.scoring || 'best_network';
  let currentEffectiveEnvironment = null;
  let environmentDefaultJobId = null;
  let currentResults = null;
  let currentResultsJobId = null;
  // Reloading the page keeps the selected results tab; opening the page again
  // from another page always starts on Scoring Charts.
  const pageReloaded = (() => {
    try { return performance.getEntriesByType('navigation')[0]?.type === 'reload'; } catch { return false; }
  })();
  let activeResultTab = (pageReloaded && restoredScoringViewState.resultTab) || 'charts';
  const showResultTab = name => {
    activeResultTab = name;
    for (const tab of root.querySelectorAll('[data-result-tab]')) {
      const selected = tab.dataset.resultTab === name;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    for (const pane of root.querySelectorAll('[data-result-pane]')) pane.hidden = pane.dataset.resultPane !== name;
  };
  showResultTab(activeResultTab);
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

  function scoringVendorName(value) {
    const raw = String(value ?? '').replace(/\s+- All(?: Vendors)?$/i, '').trim();
    const operators = uniqueCatalogueValues([
      ...operatorGroups.flatMap(operatorGroupLabels),
      ...[...datasetCatalogues.values()].flatMap(catalogue => catalogue.operators || []),
    ]).sort((left, right) => right.length - left.length);
    if (operators.some(operator => operator.toLocaleLowerCase() === raw.toLocaleLowerCase())) return raw;
    const prefix = operators.find(operator => raw.toLocaleLowerCase().startsWith(`${operator.toLocaleLowerCase()}_`));
    return prefix ? raw.slice(prefix.length + 1) : raw;
  }

  function contextFilterOptions(key, catalogueValues) {
    if (key === 'Vendor' || key === 'Operator_Vendor' || key === 'Vendor_Operator') {
      return (window.vendorOnlyFilterChoices?.(key, catalogueValues) || catalogueValues.map(value => ({value, label: value})))
        .map(choice => ({...choice, color: ''}));
    }
    if (key === 'Campaign') {
      // Shown as everywhere (2026-Q2-SA) and in chronological order; the filter keeps the full value.
      return catalogueValues.map(value => ({value, label: hierarchyDisplayValue({level: 'Campaign', value}), color: ''}))
        .sort((left, right) => insightCampaignKey(left.value) - insightCampaignKey(right.value) || left.label.localeCompare(right.label));
    }
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
      const selectedValues = new Set([...select.selectedOptions].map(option => key === 'Vendor' ? scoringVendorName(option.value) : option.value).filter(Boolean));
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
          option.selected = selectedValues.has(key === 'Vendor' ? scoringVendorName(entry.value) : entry.value);
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
    contextFilterDefinitions = contextFilterKeys(ordered).map(key => ({key, catalogueKey: filterCatalogueKeys.get(key)}));
    for (const {key} of contextFilterDefinitions) {
      const filterLabel = contextFilterSelects.get(key)?.closest('label');
      if (filterLabel && contextFilterGrid) contextFilterGrid.append(filterLabel);
    }
    for (const level of ordered) {
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
      return [key, key !== 'Vendor' && available.length && values.length === available.length ? [] : values];
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

  function restoreCalculationSelectionFromJob(job) {
    applySavedCalculationSelection({
      dataset_ids: job.dataset_ids || [],
      aggregation_levels: job.aggregation_levels || job.levels || [],
      nr_mode: job.nr_mode,
      baseline_operator: job.baseline_operator,
      scoring_profile_id: job.scoring_profile_id,
      context_filters: job.context_filters || {},
    });
    scheduleSelectionSave();
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

  function calculationPayload() {
    const levels = [...new Set(selectedLevels())];
    if (!levels.includes('Operator')) levels.unshift('Operator');
    return {
      dataset_ids: selectedDatasetIds(),
      aggregation_levels: levels,
      scoring_profile_id: scoringProfileSelect?.value || undefined,
      nr_mode: nrFilter.value || 'NSA',
      baseline_operator: baselineInput.value.trim(),
      context_filters: selectedContextFilters(),
    };
  }

  function updateCalculationMatch(ready) {
    if (submittingCalculation) return;
    const payload = calculationPayload();
    const key = ready ? JSON.stringify(payload) : '';
    if (key && key === calculationMatchKey) return;
    calculationMatchKey = key;
    const revision = ++calculationMatchRevision;
    window.clearTimeout(calculationMatchTimer);
    calculateButton.disabled = true;
    recalculateButton.disabled = true;
    if (!ready || !payload.baseline_operator) return;
    calculationMatchTimer = window.setTimeout(async () => {
      try {
        const response = await requestJson(`${jobsUrl}/match`, {method: 'POST', body: JSON.stringify(payload)});
        if (revision !== calculationMatchRevision || submittingCalculation) return;
        const existing = response.job;
        calculateButton.disabled = Boolean(existing);
        recalculateButton.disabled = !existing || isActive(existing);
        if (existing && isActive(existing)) {
          setMessage('A scoring job with these parameters is already queued or running.');
        } else if (existing) {
          setMessage('A scoring job with these parameters already exists. Use Recalculate to update it.');
        } else {
          setMessage('Ready to calculate a new scoring job.');
        }
      } catch (error) {
        if (revision === calculationMatchRevision && !submittingCalculation) {
          setMessage(error.message || 'Unable to check existing scoring jobs.', 'error');
        }
      }
    }, 180);
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
    updateCalculationMatch(ready);
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

  function datasetNameDate(name) {
    const text = String(name || '');
    const dateValue = (year, month, day) => {
      const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
      return date.getUTCFullYear() === Number(year) && date.getUTCMonth() === Number(month) - 1
        && date.getUTCDate() === Number(day) ? date.getTime() : NaN;
    };
    const formats = [
      {pattern: /(?:^|\D)((?:19|20)\d{2})[-_. ]?(\d{2})[-_. ]?(\d{2})(?!\d)/g, yearFirst: true},
      {pattern: /(?:^|\D)(\d{2})[-_. ]?(\d{2})[-_. ]?((?:19|20)\d{2})(?!\d)/g, yearFirst: false},
    ];
    for (const {pattern, yearFirst} of formats) {
      for (const match of text.matchAll(pattern)) {
        const timestamp = yearFirst ? dateValue(match[1], match[2], match[3]) : dateValue(match[3], match[2], match[1]);
        if (Number.isFinite(timestamp)) return timestamp;
      }
    }
    const yearQuarter = text.match(/(?:^|\D)((?:19|20)\d{2})[-_. ]*Q([1-4])(?!\d)/i);
    if (yearQuarter) return dateValue(yearQuarter[1], (Number(yearQuarter[2]) - 1) * 3 + 1, 1);
    const quarterYear = text.match(/(?:^|[^a-z0-9])Q([1-4])[-_. ]*((?:19|20)\d{2})(?!\d)/i);
    if (quarterYear) return dateValue(quarterYear[2], (Number(quarterYear[1]) - 1) * 3 + 1, 1);
    return NaN;
  }

  function selectLatestDatasetForEachKind(count = 1) {
    for (const input of datasetInputs) input.checked = false;
    for (const kind of datasetKindOrder) {
      const candidates = datasetOptions.filter(option => !option.hidden && String(option.dataset.datasetKind || '').toLowerCase() === kind);
      candidates.sort((left, right) => {
        const leftUploaded = Date.parse(left.dataset.uploadedAt || '');
        const rightUploaded = Date.parse(right.dataset.uploadedAt || '');
        const leftNameDate = datasetNameDate(left.dataset.datasetName);
        const rightNameDate = datasetNameDate(right.dataset.datasetName);
        const leftDate = Number.isFinite(leftNameDate) ? leftNameDate : leftUploaded;
        const rightDate = Number.isFinite(rightNameDate) ? rightNameDate : rightUploaded;
        if (Number.isFinite(leftDate) && Number.isFinite(rightDate) && leftDate !== rightDate) return rightDate - leftDate;
        if (Number.isFinite(leftDate) !== Number.isFinite(rightDate)) return Number.isFinite(leftDate) ? -1 : 1;
        const leftHasUploadDate = Number.isFinite(leftUploaded);
        const rightHasUploadDate = Number.isFinite(rightUploaded);
        if (leftHasUploadDate && rightHasUploadDate && leftUploaded !== rightUploaded) return rightUploaded - leftUploaded;
        if (leftHasUploadDate !== rightHasUploadDate) return leftHasUploadDate ? -1 : 1;
        const leftId = Number(left.querySelector('[data-dataset-id]')?.value || 0);
        const rightId = Number(right.querySelector('[data-dataset-id]')?.value || 0);
        return rightId - leftId;
      });
      for (const option of candidates.slice(0, count)) {
        const input = option.querySelector('[data-dataset-id]');
        if (input) input.checked = true;
      }
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

  function jobCdrNames(job) {
    let names = valueOf(job, ['dataset_names', 'cdr_names', 'source_names'], null);
    if (!Array.isArray(names) || !names.length) {
      const metadata = job?.source_metadata;
      const entries = Array.isArray(metadata) ? metadata : (metadata && typeof metadata === 'object' ? Object.values(metadata) : []);
      names = entries.map(entry => firstValue(entry, ['name', 'dataset_name', 'cdr_name'], '')).filter(Boolean);
    }
    return Array.isArray(names) ? uniqueCatalogueValues(names) : [];
  }

  function jobCdrSummary(job) {
    const names = jobCdrNames(job);
    if (names.length) return names.join(', ');
    const ids = valueOf(job, ['dataset_ids', 'cdr_ids'], []);
    const count = Array.isArray(ids) ? ids.length : Number(valueOf(job, ['dataset_count'], 0));
    return `${count || 'Selected'} CDR${count === 1 ? '' : 's'}`;
  }

  function savedJobFilterValues(job, key) {
    for (const filters of [job?.context_filters, job?.resolved_context_filters]) {
      if (!filters || typeof filters !== 'object') continue;
      const value = firstValue(filters, [key], null);
      if (value === null || value === undefined) continue;
      const rawValues = Array.isArray(value) ? value : [value];
      const values = uniqueCatalogueValues(key === 'Vendor' ? rawValues.map(scoringVendorName) : rawValues);
      const datasetIds = valueOf(job, ['dataset_ids', 'cdr_ids'], []);
      const catalogueKey = catalogueKeyByLevel.get(key);
      if (values.length && Array.isArray(datasetIds) && datasetIds.length
          && datasetIds.every(id => Array.isArray(datasetCatalogues.get(String(id))?.[catalogueKey]))) {
        const available = new Set(datasetIds.flatMap(id => datasetCatalogues.get(String(id))[catalogueKey])
          .map(item => String(key === 'Vendor' ? scoringVendorName(item) : item).trim().toLocaleLowerCase()).filter(Boolean));
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
    const campaigns = campaignFilter.length
      ? [...new Set(campaignFilter.map(value => hierarchyDisplayValue({level: 'Campaign', value})))]
        .sort((left, right) => insightCampaignKey(left) - insightCampaignKey(right) || left.localeCompare(right))
      : jobCampaigns(job).filter(value => value !== 'Unspecified');
    const campaignValue = campaigns.length ? campaigns.join(', ') : 'All Campaigns';
    return [
      {dimension: 'neutral', value: formatDate(valueOf(job, ['created_at', 'submitted_at', 'started_at'], ''))},
      {dimension: 'nr-mode', value: valueOf(job, ['nr_mode'], 'All NR Modes')},
      {dimension: 'region', value: filterValue('Region', 'All Regions')},
      {dimension: 'cluster', value: filterValue('Cluster', 'All Clusters')},
      {dimension: 'city', value: filterValue('City', 'All Cities')},
      {dimension: 'operator', value: filterValue('Operator', 'All Operators')},
      {dimension: 'vendor', value: filterValue('Vendor', 'All Vendors')},
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
    // Shown as everywhere (2026-Q2-SA), in chronological order.
    const unique = [...new Set(campaigns.map(value => hierarchyDisplayValue({level: 'Campaign', value})))]
      .sort((left, right) => insightCampaignKey(left) - insightCampaignKey(right) || left.localeCompare(right));
    return unique.length ? unique : ['Unspecified'];
  }

  function jobLevels(job) {
    const levels = valueOf(job, ['aggregation_levels', 'levels'], []);
    return Array.isArray(levels) ? (levels.length ? levels.join(' → ') : 'Operator') : String(levels || 'Operator');
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
      return rightDate - leftDate || Number(right.id || 0) - Number(left.id || 0);
    });
  }

  function syncJobLists() {
    for (const list of jobLists.slice(1)) {
      list.replaceChildren(...Array.from(jobList.children, row => row.cloneNode(true)));
    }
  }

  function renderJobs() {
    const ordered = sortedJobs(jobs);
    for (const countBadge of root.querySelectorAll('[data-job-count]')) {
      countBadge.textContent = `${ordered.length} job${ordered.length === 1 ? '' : 's'}`;
    }
    jobList.replaceChildren();
    selectedJobCard.textContent = ordered.length ? 'Select a scoring job' : 'No saved scoring jobs';
    if (!ordered.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No scoring jobs have been run in this workspace.';
      jobList.append(empty);
      syncJobLists();
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
      const aggregation = document.createElement('span');
      aggregation.className = 'scoring-job-aggregation';
      const aggregationLabel = document.createElement('span');
      aggregationLabel.textContent = 'Aggregation levels:';
      const aggregationLevels = document.createElement('strong');
      aggregationLevels.textContent = jobLevels(job);
      aggregation.append(aggregationLabel, aggregationLevels);
      button.append(aggregation);
      const meta = document.createElement('span');
      meta.className = 'scoring-job-meta';
      const baseline = valueOf(job, ['baseline_operator'], 'EE');
      meta.textContent = 'GAP Reference: ';
      const referenceValue = document.createElement('strong');
      referenceValue.className = 'scoring-job-reference';
      referenceValue.textContent = baseline;
      meta.append(referenceValue);
      button.append(meta);
      const cdrNames = jobCdrNames(job);
      const cdrButton = document.createElement('button');
      cdrButton.type = 'button';
      cdrButton.className = 'scoring-job-cdrs';
      cdrButton.dataset.jobCdrs = id;
      const cdrCount = cdrNames.length || (job.dataset_ids || []).length;
      cdrButton.textContent = cdrCount ? `${cdrCount} CDR${cdrCount === 1 ? '' : 's'}` : 'Selected CDRs';
      cdrButton.title = cdrNames.length ? cdrNames.join('\n') : jobCdrSummary(job);
      cdrButton.setAttribute('aria-label', `Show CDRs for scoring job ${id}`);
      const profileName = valueOf(job, ['scoring_profile_name', 'profile_name'], '');
      if (profileName) {
        const profileMeta = document.createElement('span');
        profileMeta.className = 'scoring-job-meta';
        profileMeta.textContent = 'Scoring Methodology: ';
        const profileValue = document.createElement('strong');
        profileValue.className = 'scoring-job-profile';
        profileValue.textContent = profileName;
        profileMeta.append(profileValue);
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
      if (id === selectedJobId) {
        selectedJobCard.replaceChildren(...Array.from(button.children, child => child.cloneNode(true)), cdrButton.cloneNode(true));
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
      row.append(button, cdrButton, remove);
      jobList.append(row);
    }
    syncJobLists();
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

  function syncResultTableControls() {
    const controls = root.querySelector('[data-scoring-results-value-row]');
    if (controls) controls.hidden = activeResultTab !== 'scoring';
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
    const isGapKpiTable = Array.isArray(tableData.rows)
      && (typeof tableData.operator === 'string'
        || tableData.rows.some(row => row?.gaps && !row?.values));
    const total = tableData[totalKey] && typeof tableData[totalKey] === 'object'
      ? tableData[totalKey] : tableData.total;
    return {
      ...tableData,
      _display_mode: mode,
      rows: mode === 'summary' && isGapKpiTable ? tableData.rows : tableData[rowsKey],
      total,
      ...(total && Object.hasOwn(total, 'gap_points') ? {total_gap_points: total.gap_points} : {}),
      ...(total && Object.hasOwn(total, 'gap_partial') ? {total_gap_partial: total.gap_partial} : {}),
      ...(total && Object.hasOwn(total, 'gap_environments') ? {total_gap_environments: total.gap_environments} : {}),
    };
  }

  function effectiveScoring(payload = typeof currentResults === 'undefined' ? null : currentResults) {
    const requested = typeof selectedScoring === 'undefined' ? 'best_network' : selectedScoring;
    return requested === 'most_reliable' && payload?.scorings?.most_reliable ? 'most_reliable' : 'best_network';
  }

  function scoringLabel() {
    return effectiveScoring() === 'most_reliable' ? 'Most Reliable Network' : 'Best Network';
  }

  // The selected scoring's results, in the shape of a Best Network payload.
  function activeScoringPayload(payload = currentResults) {
    if (!payload || effectiveScoring(payload) !== 'most_reliable') return payload;
    const reliable = payload.scorings.most_reliable;
    return {
      ...payload, views: reliable.views || {}, configuration: reliable.configuration,
      notices: reliable.notices || [], warnings: reliable.warnings || [], coverage_notes: reliable.coverage_notes || {},
      environment_scaling: reliable.environment_scaling || null, totals: reliable.totals || [],
      charts: reliable.totals || [], gap_totals: reliable.gap_totals || [], scoring: [], gap: [],
    };
  }

  function activeScoringConfiguration() {
    return effectiveScoring() === 'most_reliable'
      ? activeScoringPayload()?.configuration || {}
      : selectedJob?.configuration || currentResults?.configuration || {};
  }

  function syncResultScoring(payload) {
    if (!scoringKindControl || !scoringKindSelect) return;
    const available = Boolean(payload?.scorings?.most_reliable);
    scoringKindControl.hidden = !available;
    scoringKindSelect.disabled = !available;
    scoringKindSelect.value = effectiveScoring(payload);
  }

  function setExportLinks(jobId, enabled) {
    for (const [kind, selector] of [['scoring', '[data-export-scoring]'], ['gap', '[data-export-gap]'], ['ppt', '[data-export-ppt]']]) {
      const link = root.querySelector(selector);
      link.hidden = false;
      link.setAttribute('aria-disabled', String(!enabled));
      link.tabIndex = enabled ? 0 : -1;
      const query = `table_mode=${encodeURIComponent(selectedTableMode())}&gap_layout=${encodeURIComponent(selectedGapLayout())}&environment=${encodeURIComponent(selectedEnvironment || 'all')}`;
      const gapOption = kind === 'ppt' ? `&show_gap_values=${showGapValues() ? 'true' : 'false'}` : '';
      // CSV files carry the selected scoring; PowerPoint and Word carry both scorings.
      const scoringOption = kind !== 'ppt' && typeof effectiveScoring === 'function'
        && effectiveScoring() === 'most_reliable' ? '&scoring=most_reliable' : '';
      link.href = enabled ? `${exportBase}/${encodeURIComponent(jobId)}/export/${kind}?${query}${gapOption}${scoringOption}` : '#';
    }
  }

  function pptHasDenseCharts(payload, environment) {
    const views = payload?.views || payload?.scoring_views || payload || {};
    const hierarchy = Array.isArray(views.hierarchy_score_tables) ? views.hierarchy_score_tables : [];
    const tables = hierarchy.length ? hierarchy : (views.score_tables || []);
    return tables.some(table => {
      if (environment !== 'all' && environmentOf(table) !== environment) return false;
      const bestNetworkBars = table.hierarchy_columns?.length || table.operators?.length || 0;
      const categories = new Set((table.rows || []).map(row => row.category)).size;
      const categoryBars = categories * bestNetworkBars;
      return bestNetworkBars > 20 || categoryBars > 40;
    });
  }

  async function generateScoringPpt(link) {
    let splitCharts = false;
    if (pptHasDenseCharts(currentResults, selectedEnvironment || 'all')) {
      const message = 'Some Best Network charts contain more than 20 bars or Scoring charts contain more than 40 bars. Split charts across multiple slides?';
      const choice = typeof showConfirmDialog === 'function'
        ? await showConfirmDialog(message, {
          title: 'PowerPoint chart layout', confirmLabel: 'Yes, split charts',
          secondaryLabel: 'No, keep all bars on one slide', cancelLabel: 'Cancel', wideActions: true,
        })
        : (window.confirm(message) ? 'confirm' : 'secondary');
      if (choice !== 'confirm' && choice !== 'secondary') return;
      splitCharts = choice === 'confirm';
    }
    const url = new URL(link.href, window.location.href);
    url.searchParams.set('split_charts', String(splitCharts));
    await downloadScoringDocument(url.href, 'PowerPoint');
  }

  // A progress dialog stays open while the document is generated, then the browser downloads it.
  // The PowerPoint and Word exports open the report editor: one or more scenarios with
  // their filters, aggregation and the content of each scoring, from the selected job's CDRs.
  async function openScoringReport(format) {
    const jobId = currentResultsJobId || selectedJobId;
    if (!jobId || !window.ScoringReportEditor) return false;
    const filterOptions = Object.fromEntries(contextFilterDefinitions.map(({key}) => [key,
      [...(contextFilterSelects.get(key)?.options || [])].filter(option => option.value && !option.disabled).map(option => option.value)]));
    const job = selectedJob || currentResults?.job || {};
    const defaults = {
      filters: job.context_filters || {}, levels: job.aggregation_levels || job.levels || ['Operator'],
      mainCities: false, operators: filterOptions.Operator || [],
    };
    let state = null;
    try {
      const response = await fetch('/api/scoring/report-configurations', {credentials: 'same-origin'});
      if (response.ok) state = await response.json();
    } catch (_error) {
      state = null;
    }
    const choice = await window.ScoringReportEditor.open({
      title: 'Scoring & GAP Analysis report',
      configuration: state?.last || window.ScoringReportEditor.defaultConfiguration(defaults),
      context: {filterOptions, operators: filterOptions.Operator || [], mainCities, defaults, operatorGroups},
      actions: format === 'word' ? [['word', 'Generate Word'], ['ppt', 'Generate PowerPoint']]
        : [['ppt', 'Generate PowerPoint'], ['word', 'Generate Word']],
    });
    if (!choice) return true;
    await downloadScoringDocument(`${exportBase}/${encodeURIComponent(jobId)}/report/${choice.action}`,
      choice.action === 'word' ? 'Word' : 'PowerPoint', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({configuration: choice.configuration, split_charts: true}),
      });
    return true;
  }

  async function downloadScoringDocument(href, label, init = {}) {
    globalThis.showLoadingOverlay?.(`Preparing the ${label} document`,
      `Preparing the Scoring & GAP Analysis ${label} of the selected job with its tables and charts. The document downloads when it is ready.`);
    try {
      const response = await fetch(href, {credentials: 'same-origin', ...init});
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === 'string' ? payload.detail : `The ${label} export failed.`);
      }
      const disposition = response.headers.get('Content-Disposition') || '';
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
      const plain = /filename="([^"]+)"/i.exec(disposition)?.[1];
      const name = encoded ? decodeURIComponent(encoded) : plain || `Scoring & GAP Analysis.${label === 'Word' ? 'docx' : 'pptx'}`;
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = name;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      globalThis.hideLoadingOverlay?.();
      if (typeof showInfoDialog === 'function') showInfoDialog(error.message, {tone: 'error', title: 'The document could not be generated'});
      else window.alert(error.message);
    } finally {
      globalThis.hideLoadingOverlay?.();
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
      if (['category', 'total'].includes(String(row?.row_type || '').toLocaleLowerCase())) tr.classList.add('scoring-total-row');
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

  function gapComparisonIdentity(table, kind) {
    return JSON.stringify([selectedJobId || currentResultsJobId || '', kind, comparisonIdentity(table, kind)]);
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

  function contextLabel(context, {environmentPrefix = true} = {}) {
    if (!context || typeof context !== 'object') return '';
    const preferred = ['campaign', 'region', 'cluster', 'city', 'vendor', 'dataset_type', 'environment'];
    const entries = preferred.filter(key => context[key] !== null && context[key] !== undefined && context[key] !== '')
      .map(key => [key, key === 'environment' ? environmentLabel(String(context[key]))
        : key === 'campaign' ? hierarchyDisplayValue({level: 'Campaign', value: context[key]}) : context[key]]);
    for (const [key, value] of Object.entries(context)) {
      if (!preferred.includes(key) && value !== null && value !== undefined && value !== '') entries.push([key, key === 'environment' ? environmentLabel(String(value)) : value]);
    }
    return entries.map(([key, value]) => key === 'environment' && !environmentPrefix
      ? String(value) : `${humanizeKey(key)}: ${value}`).join(' · ');
  }

  function appendContextHeader(pane, table, kind, titlePrefix = '') {
    const heading = document.createElement('h4');
    heading.className = 'scoring-context-heading';
    heading.textContent = titlePrefix || (kind === 'gap' || kind === 'gap-summary' ? 'GAP Analysis' : 'Scoring Tables');
    const context = table?.context && typeof table.context === 'object' ? table.context : {};
    const environment = context.environment;
    if (environment !== null && environment !== undefined && environment !== '') {
      const separator = document.createElement('span');
      separator.className = 'scoring-context-separator';
      separator.ariaHidden = 'true';
      separator.textContent = '—';
      const environmentChip = document.createElement('span');
      environmentChip.className = 'scoring-context-chip scoring-environment-chip';
      environmentChip.textContent = `Environment: ${environmentLabel(String(environment))}`;
      heading.append(separator, environmentChip);
    }
    pane.append(heading);

    const preferred = ['campaign', 'region', 'cluster', 'city', 'vendor', 'dataset_type', 'environment'];
    const entries = preferred.filter(key => key !== 'environment' && context[key] !== null && context[key] !== undefined && context[key] !== '')
      .map(key => [key, key === 'environment' ? environmentLabel(String(context[key]))
        : key === 'campaign' ? hierarchyDisplayValue({level: 'Campaign', value: context[key]}) : context[key]]);
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
    if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return 'N/A*';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'N/A*';
    if (signed && numeric > 0) return `+${numeric.toFixed(2)}`;
    if (signed && numeric < 0) return `−${Math.abs(numeric).toFixed(2)}`;
    return numeric.toFixed(2);
  }

  function formatScoreCell(cell) {
    if (!cell || typeof cell !== 'object') return {text: 'N/A*', complete: false};
    const points = firstValue(cell, ['points', 'weighted_points', 'weighted_score'], null);
    const complete = firstValue(cell, ['complete', 'complete_coverage'], false) === true;
    if (points === null || points === undefined || (typeof points === 'string' && points.trim() === '')) return {text: 'N/A*', complete: false};
    const numeric = Number(points);
    if (!Number.isFinite(numeric)) return {text: 'N/A*', complete: false};
    return {text: `${numeric.toFixed(2)}${complete ? '' : '*'}`, complete};
  }

  function formatRawKpiValue(value) {
    if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return 'N/A*';
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

  function appendOperatorRankingLegend(pane) {
    const container = document.createElement('div');
    container.className = 'scoring-threshold-legend scoring-operator-ranking-legend';
    for (const [label, color] of [['Best operator', '#C6EFCE'], ['Worst operator', '#FFC7CE']]) {
      const item = document.createElement('span');
      item.className = 'scoring-legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'scoring-legend-swatch';
      swatch.style.backgroundColor = color;
      swatch.setAttribute('aria-hidden', 'true');
      const copy = document.createElement('strong');
      copy.textContent = label;
      item.append(swatch, copy);
      container.append(item);
    }
    pane.append(container);
  }

  function summaryOperatorColors(values, columns) {
    const entries = [];
    for (const column of columns) {
      const cell = operatorValue(values, column.id);
      const points = firstValue(cell, ['points', 'weighted_points', 'weighted_score'], null);
      if (points === null || points === undefined || (typeof points === 'string' && !points.trim())) continue;
      const numeric = Number(points);
      if (!Number.isFinite(numeric)) continue;
      entries.push({id: column.id, points: numeric});
    }
    const colors = new Map();
    if (entries.length >= 2) {
      const maximum = Math.max(...entries.map(entry => entry.points));
      const minimum = Math.min(...entries.map(entry => entry.points));
      for (const entry of maximum === minimum ? [] : entries) {
        if (entry.points === maximum) colors.set(entry.id, '#C6EFCE');
        else if (entry.points === minimum) colors.set(entry.id, '#FFC7CE');
      }
    }
    return colors;
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

  function styleIncompleteValue(element) {
    if (element.textContent === 'N/A') element.textContent = 'N/A*';
    if (!element.textContent.endsWith('*')) return;
    element.style.color = '#c62828';
    element.style.fill = '#c62828';
    element.style.fontWeight = '700';
  }

  function addMatrixScoreCell(row, cell, className = '', isTotal = false, summaryColor = null) {
    const td = document.createElement('td');
    td.dataset.numeric = 'true';
    td.dataset.column = 'score';
    const formatted = formatScoreCell(cell);
    td.textContent = formatted.text;
    if (className) td.className = className;
    styleIncompleteValue(td);
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
    if (summaryColor !== null) {
      td.style.backgroundColor = summaryColor;
      if (summaryColor) td.dataset.operatorRank = summaryColor === '#C6EFCE' ? 'best' : 'worst';
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
    styleIncompleteValue(td);
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

  function appendGapTotals(table, rows, columnIds) {
    const footer = document.createElement('tfoot');
    const row = document.createElement('tr');
    row.className = 'scoring-total-row';
    row.style.fontWeight = '700';
    const label = document.createElement('td');
    label.colSpan = 3;
    label.textContent = 'Total KPI GAP';
    label.style.backgroundColor = '#D7E0E5';
    row.append(label);
    for (const columnId of columnIds) {
      const values = rows.map(item => columnId === null ? item?.gap_points : item?.gaps?.[columnId]);
      const valid = values.filter(value => value !== null && value !== undefined && value !== ''
        && Number.isFinite(Number(value))).map(Number);
      const partial = valid.length < values.length || rows.some(item => columnId === null
        ? item?.gap_partial === true : item?.gap_partial?.[columnId] === true);
      addMatrixGapCell(row, valid.length ? valid.reduce((sum, value) => sum + value, 0) : null,
        '#D7E0E5', partial);
      row.lastElementChild.title = 'Sum of available KPI GAP points in this column.'
        + (partial ? ' Incomplete coverage: some KPI contributions are missing or partial.' : '');
    }
    footer.append(row);
    table.append(footer);
  }

  function orderGapRows(rows, valuesForRow, sortByGap = true) {
    const gapMean = item => {
      const values = valuesForRow(item)
        .filter(value => value !== null && value !== undefined
          && typeof value !== 'boolean' && String(value).trim() !== '')
        .map(Number).filter(Number.isFinite);
      return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    };
    const compare = (left, right) => {
      const leftGap = gapMean(left);
      const rightGap = gapMean(right);
      if (leftGap === null) return rightGap === null ? 0 : 1;
      if (rightGap === null) return -1;
      return leftGap - rightGap;
    };
    const kpis = rows.filter(item => item?.row_type !== 'category');
    if (sortByGap) kpis.sort(compare);
    return kpis;
  }

  function applyGapCategoryRunColors(tbody) {
    const colors = ['#edf3f8', '#e3ecf3'];
    [...tbody.querySelectorAll('td.scoring-category-cell')].forEach((cell, index) => {
      cell.style.setProperty('background-color', colors[index % colors.length], 'important');
    });
  }

  function appendGapOrderNotice(parent, sortByGap = true) {
    if (!sortByGap) return;
    const notice = document.createElement('p');
    notice.className = 'scoring-priority-order-notice';
    const text = document.createElement('strong');
    text.textContent = 'KPIs are ordered by GAP, from lowest to highest.';
    notice.append(text);
    parent.append(notice);
  }

  function appendGapScaleAside(parent, tableData, rows, sortByGap = true) {
    parent.style.display = 'flex';
    parent.style.alignItems = 'center';
    parent.style.flexWrap = 'wrap';
    parent.style.gap = '.55rem 1rem';
    parent.style.marginBottom = '.55rem';
    const explanation = parent.querySelector('.scoring-context-note');
    if (explanation) {
      explanation.style.flex = '1 1 30rem';
      explanation.style.margin = '0';
    }
    const aside = document.createElement('div');
    aside.className = 'scoring-gap-info-aside';
    aside.style.display = 'flex';
    aside.style.flexDirection = 'column';
    aside.style.alignItems = 'flex-end';
    aside.style.gap = '.15rem';
    aside.style.marginLeft = 'auto';
    appendGapOrderNotice(aside, sortByGap);
    const notice = aside.querySelector('.scoring-priority-order-notice');
    if (notice) notice.style.cssText = 'margin: 0; text-align: right;';
    appendPriorityGapScale(aside, tableData, rows);
    const scale = aside.querySelector('.scoring-gap-scale');
    if (scale) scale.style.cssText = 'margin: 0; justify-content: flex-end;';
    parent.append(aside);
  }

  function appendMatrixTable(pane, tableData) {
    const isSummary = tableData?._display_mode === 'summary';
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
    for (const [columnIndex, title] of [...(!isSummary ? ['CATEGORY'] : []), isSummary ? 'CATEGORY' : 'KPI', ...(!isSummary ? ['Type of KPI'] : []), 'Score weight (%)', 'Max score'].entries()) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.rowSpan = 2;
      th.dataset.column = columnIndex === 0 && !isSummary ? 'category'
        : ({CATEGORY: 'kpi', KPI: 'kpi', 'Type of KPI': 'type', 'Score weight (%)': 'weight', 'Max score': 'maximum'})[title];
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
        th.style.setProperty('--operator-text', readableTextColor(presentation.color));
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
      if (run && !isSummary) {
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
      if (!isSummary) tr.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));

      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(item?.weight_percent);
      styleIncompleteValue(weight);
      tr.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(item?.max_points);
      styleIncompleteValue(maximum);
      tr.append(maximum);

      const values = item?.values && typeof item.values === 'object' ? item.values : {};
      const summaryColors = isSummary ? summaryOperatorColors(values, operators.map(id => ({id}))) : new Map();
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
          styleIncompleteValue(cell);
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
          isSummary ? (summaryColors.get(operator) || '') : null,
        ),
        operator => addMatrixGapCell(tr, firstValue(gaps, [operator], null), firstValue(gapColors, [operator], ''),
          firstValue(gapPartial, [operator], false), firstValue(gapEnvironments, [operator], [])),
      );
      tbody.append(tr);
    });

    if (!isSummary) applyGapCategoryRunColors(tbody);
    table.append(thead, tbody);
    const total = tableData?.total;
    if (total && typeof total === 'object') {
      const tfoot = document.createElement('tfoot');
      const row = document.createElement('tr');
      const category = document.createElement('th');
      category.scope = 'row';
      category.dataset.column = 'category';
      category.textContent = 'Total';
      if (!isSummary) row.append(category);
      const label = document.createElement('td');
      label.dataset.column = 'kpi';
      label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
      row.append(label);
      if (!isSummary) row.append(createKpiTypeCell('', true));
      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(firstValue(total, ['weight_percent'], 100));
      styleIncompleteValue(weight);
      row.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(firstValue(total, ['max_points'], null));
      styleIncompleteValue(maximum);
      row.append(maximum);
      const values = total.values && typeof total.values === 'object' ? total.values : {};
      const summaryColors = isSummary ? summaryOperatorColors(values, operators.map(id => ({id}))) : new Map();
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
        operator => addMatrixScoreCell(row, operatorValue(values, operator), '', true, isSummary ? (summaryColors.get(operator) || '') : null),
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

  // Campaigns as the workspace Campaign Maps show them (campaign_labels.js); without it,
  // the default map: 2026-Q2, 2026-Q2-NSA or 2026-Q2-SA.
  function hierarchyDisplayValue(entry) {
    const text = String(entry?.value ?? 'Not specified');
    if (entry?.level !== 'Campaign') return text;
    if (typeof globalThis.campaignLabel === 'function') return globalThis.campaignLabel(text) || text;
    const year = text.match(/(?<!\d)((?:19|20)\d{2})(?!\d)/)?.[1];
    const quarter = text.match(/(?:^|[^A-Z0-9])Q\s*[_\- ]?([1-4])(?=$|[^0-9])/i)?.[1];
    const mode = (text.match(/(?:^|[_\- ])(NSA|SA)(?=$|[_\- ])/i)?.[1] || '').toUpperCase();
    return year && quarter ? `${year}-Q${quarter}${mode ? `-${mode}` : ''}` : text;
  }

  function hierarchyPathEntry(column, depth, levels) {
    const path = Array.isArray(column?.path) ? column.path : [];
    const expectedLevel = levels[depth] || '';
    const entry = path.find(item => String(item?.level || '') === expectedLevel) || path[depth] || {};
    return {
      level: String(entry?.level || expectedLevel || `Level ${depth + 1}`),
      value: hierarchyDisplayValue(entry),
      rawValue: String(entry?.value ?? ''),
    };
  }

  function hierarchyPathValueLabel(column) {
    const path = Array.isArray(column?.path) ? column.path : [];
    return path.map(entry => {
      const value = hierarchyDisplayValue(entry).trim();
      return value || 'Not specified';
    }).join(' · ');
  }

  function hierarchyPathFullLabel(column) {
    const path = Array.isArray(column?.path) ? column.path : [];
    return String(path.length ? path.map(entry => {
      const level = String(entry?.level || 'Level');
      const value = hierarchyDisplayValue(entry).trim() || 'Not specified';
      return `${level}: ${value}`;
    }).join(' · ') : column?.label || '');
  }

  function appendHierarchyAxisBands(svg, categories, levels, columnsById, categoryStarts, step, baselineY, left, right) {
    if (!levels.length || !categories.length) return;
    const rowHeight = 32;
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
        const maxCharacters = Math.max(3, Math.min(34, Math.floor((groupWidth - 8) / 8.5)));
        const lines = fittedSvgLabelLines(value, maxCharacters, 2);
        const label = svgElement(svg, 'text', {
          x: x1 + groupWidth / 2,
          y: y + rowHeight / 2 + (lines.length > 1 ? -4 : 5),
          'text-anchor': 'middle',
          class: 'scoring-chart-hierarchy-label',
          'aria-label': `${entry.level}: ${value}`,
        });
        label.setAttribute('fill', '#334b58');
        label.setAttribute('pointer-events', 'auto');
        lines.forEach((line, lineIndex) => {
          const span = svgElement(svg, 'tspan', {x: x1 + groupWidth / 2, dy: lineIndex ? '15' : '0'});
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
      return [entry.level, entry.rawValue];
    }));
  }

  function appendHierarchyHeaders(thead, tableData, columns, fixedHeadings, blocks, gapBaseline = null) {
    const levels = hierarchyLevelNames(tableData, columns);
    const depth = Math.max(levels.length, ...columns.map(column => Array.isArray(column.path) ? column.path.length : 0));
    const headerLevels = levels.length ? levels : Array.from({length: depth}, (_, index) => `Level ${index + 1}`);
    const firstRow = document.createElement('tr');
    for (const [title, key, className = ''] of fixedHeadings) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.rowSpan = depth + (gapBaseline ? 0 : 1);
      th.dataset.column = key;
      th.textContent = title;
      if (className) th.className = className;
      firstRow.append(th);
    }
    for (const block of gapBaseline ? [] : blocks) {
      if (!block.columns.length) continue;
      const th = document.createElement('th');
      th.scope = 'colgroup';
      th.colSpan = block.columns.length;
      th.className = `scoring-column-group ${block.className || ''}`.trim();
      th.textContent = block.label;
      firstRow.append(th);
    }
    if (!gapBaseline) thead.append(firstRow);

    for (let depthIndex = 0; depthIndex < depth; depthIndex += 1) {
      const row = gapBaseline && depthIndex === 0 ? firstRow : document.createElement('tr');
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
            if (presentation.color) {
              th.style.setProperty('--operator-accent', presentation.color);
              th.style.setProperty('--operator-text', categoryLegendTextColor(presentation.color));
            }
            if (gapBaseline) {
              th.textContent = `${canonicalOperatorName(entry.value) || entry.value} − ${gapBaseline}`;
              th.classList.add('scoring-gap-operator-header');
              th.style.setProperty('--operator-text', categoryLegendTextColor(presentation.color));
            }
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
    const isSummary = tableData?._display_mode === 'summary';
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
      ...(!isSummary ? [['CATEGORY', 'category']] : []), [isSummary ? 'CATEGORY' : 'KPI', 'kpi'],
      ...(!isSummary ? [['Type of KPI', 'type']] : []),
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
      if (!isSummary && (index === 0 || String(rows[index - 1]?.category || 'Other') !== category)) {
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
      if (!isSummary) row.append(createKpiTypeCell(item?.kpi_type, item?.row_type === 'category'));
      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(item?.weight_percent);
      styleIncompleteValue(weight);
      row.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(item?.max_points);
      styleIncompleteValue(maximum);
      row.append(maximum);
      const values = item?.values && typeof item.values === 'object' ? item.values : {};
      const summaryColors = isSummary ? summaryOperatorColors(values, allColumns) : new Map();
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
          styleIncompleteValue(cell);
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
          isSummary ? (summaryColors.get(column.id) || '') : null,
        ),
        column => addMatrixGapCell(row, firstValue(gaps, [column.id], null), firstValue(gapColors, [column.id], ''),
          firstValue(gapPartial, [column.id], false), firstValue(gapEnvironments, [column.id], [])),
      );
      tbody.append(row);
    }
    if (!isSummary) applyGapCategoryRunColors(tbody);
    table.append(thead, tbody);
    const total = tableData?.total;
    if (total && typeof total === 'object') {
      const tfoot = document.createElement('tfoot');
      const row = document.createElement('tr');
      const category = document.createElement('th');
      category.scope = 'row';
      category.dataset.column = 'category';
      category.textContent = 'Total';
      if (!isSummary) row.append(category);
      const label = document.createElement('td');
      label.dataset.column = 'kpi';
      label.textContent = showGapValues() && total.gap_label ? `Weighted score · ${total.gap_label}` : 'Weighted score';
      row.append(label);
      if (!isSummary) row.append(createKpiTypeCell('', true));
      const weight = document.createElement('td');
      weight.dataset.numeric = 'true';
      weight.dataset.column = 'weight';
      weight.textContent = formatMatrixNumber(firstValue(total, ['weight_percent'], 100));
      styleIncompleteValue(weight);
      row.append(weight);
      const maximum = document.createElement('td');
      maximum.dataset.numeric = 'true';
      maximum.dataset.column = 'maximum';
      maximum.textContent = formatMatrixNumber(firstValue(total, ['max_points'], null));
      styleIncompleteValue(maximum);
      row.append(maximum);
      const values = total.values && typeof total.values === 'object' ? total.values : {};
      const summaryColors = isSummary ? summaryOperatorColors(values, allColumns) : new Map();
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
        column => addMatrixScoreCell(row, operatorValue(values, column.id), '', true, isSummary ? (summaryColors.get(column.id) || '') : null),
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
    appendScoringGapScale(pane, tableData);
    const summarySection = document.createElement('section');
    summarySection.className = 'scoring-table-mode-section';
    const summaryHeading = document.createElement('h4');
    summaryHeading.className = 'scoring-table-section-title';
    summaryHeading.textContent = 'Scoring Tables — Summary';
    summarySection.append(summaryHeading);
    appendOperatorRankingLegend(summarySection);
    appendHierarchyMatrixTable(summarySection, tableForMode(tableData, 'summary'));
    pane.append(summarySection);
    const expandedSection = document.createElement('section');
    expandedSection.className = 'scoring-table-mode-section';
    const expandedHeading = document.createElement('h4');
    expandedHeading.className = 'scoring-table-section-title';
    expandedHeading.textContent = 'Scoring Tables — Breakdown';
    expandedSection.append(expandedHeading);
    appendThresholdLegend(expandedSection, thresholdLegend.length ? thresholdLegend : tableData?.threshold_legend);
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
    const comparisonStateKey = gapComparisonIdentity(tableData, 'hierarchy-gap');
    let comparison = gapComparisonSelections.get(comparisonStateKey) || 'all';
    const selectedOperator = comparison.startsWith('operator:') ? comparison.slice('operator:'.length) : null;
    if (selectedOperator && !operators.includes(selectedOperator)) comparison = 'all';
    gapComparisonSelections.set(comparisonStateKey, comparison);
    const columns = comparison === 'all'
      ? allColumns
      : allColumns.filter(column => hierarchyColumnOperator(column) === selectedOperator);
    const sortByGap = comparison !== 'all';
    const rows = orderGapRows(Array.isArray(tableData.rows) ? tableData.rows : [],
      item => columns.map(column => firstValue(item?.gaps || {}, [column.id], null)), sortByGap);
    const comparisonLabel = comparison === 'all' ? `All vs ${baseline}` : `${selectedOperator} vs ${baseline}`;
    const scaleRows = rows.flatMap(item => columns.map(column => ({gap_points: firstValue(item?.gaps || {}, [column.id], null)})))
      .filter(item => item.gap_points !== null && item.gap_points !== undefined && Number.isFinite(Number(item.gap_points)));
    appendContextHeader(pane, tableData, 'gap', 'GAP Analysis');
    if (operators.length) {
      const controls = document.createElement('div');
      controls.className = 'scoring-comparison-controls scoring-gap-comparison-controls';
      const label = document.createElement('label');
      label.textContent = 'GAP comparison';
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
    note.textContent = `KPI GAP compares ${comparison === 'all' ? 'each hierarchy leaf' : selectedOperator} with ${baseline} at the same context.`;
    const gapInfo = document.createElement('div');
    gapInfo.className = 'scoring-gap-info';
    gapInfo.append(note);
    pane.append(gapInfo);
    if (!columns.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = 'No operators can be compared with the selected reference operator.';
      pane.append(empty);
      return;
    }
    appendGapScaleAside(gapInfo, tableData, scaleRows, comparison !== 'all');

    const blocks = [{label: comparisonLabel, className: 'scoring-gap-group', headerClass: 'scoring-gap-header', column: 'gap', columns}];
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-priority-table scoring-gap-summary-table scoring-hierarchy-table';
    const thead = document.createElement('thead');
    appendHierarchyHeaders(thead, styleSource, columns, [
      ['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type'],
    ], blocks, baseline);
    const tbody = document.createElement('tbody');
    for (let index = 0; index < rows.length; index += 1) {
      const item = rows[index];
      const row = document.createElement('tr');
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
      const category = String(item?.category ?? '');
      const previous = rows[index - 1];
      const startsCategoryRun = index === 0
        || String(previous?.category ?? '') !== category;
      if (startsCategoryRun) {
        let span = 1;
        while (index + span < rows.length
          && String(rows[index + span]?.category ?? '') === category) span += 1;
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
    applyGapCategoryRunColors(tbody);
    table.append(thead, tbody);
    appendGapTotals(table, rows, columns.map(column => column.id));
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
    appendScoringGapScale(pane, selected);
    const summarySection = document.createElement('section');
    summarySection.className = 'scoring-table-mode-section';
    const summaryHeading = document.createElement('h4');
    summaryHeading.className = 'scoring-table-section-title';
    summaryHeading.textContent = 'Scoring Tables — Summary';
    summarySection.append(summaryHeading);
    appendOperatorRankingLegend(summarySection);
    appendMatrixTable(summarySection, tableForMode(selected, 'summary'));
    pane.append(summarySection);
    const expandedSection = document.createElement('section');
    expandedSection.className = 'scoring-table-mode-section';
    const expandedHeading = document.createElement('h4');
    expandedHeading.className = 'scoring-table-section-title';
    expandedHeading.textContent = 'Scoring Tables — Breakdown';
    expandedSection.append(expandedHeading);
    appendThresholdLegend(expandedSection, thresholdLegend.length ? thresholdLegend : selected?.threshold_legend);
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
    const rows = orderGapRows((Array.isArray(selected?.rows) ? selected.rows : []).filter(row => (
      row?.row_type === 'category' || row?.row_type === 'kpi'
      || (row?.gap_points !== null && row?.gap_points !== undefined && String(row.gap_points).trim() !== '' && Number.isFinite(Number(row.gap_points)))
    )), item => [item?.gap_points]);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = `No comparable signed KPI GAPs were found for ${operator} against ${baseline} in this comparison context.`;
      pane.append(empty);
      return;
    }
    const gapInfo = document.createElement('div');
    gapInfo.className = 'scoring-gap-info';
    appendGapScaleAside(gapInfo, selected, rows);
    pane.append(gapInfo);
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-matrix-wrap';
    const table = document.createElement('table');
    table.className = 'scoring-comparison-table scoring-priority-table';
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const [title, key] of [['Category', 'category'], ['KPI', 'kpi'], ['Type of KPI', 'type'], [`GAP (${operator} − ${baseline})`, 'gap']]) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = title;
      th.dataset.column = key;
      if (key === 'gap') th.className = 'scoring-gap-header';
      header.append(th);
    }
    thead.append(header);
    const tbody = document.createElement('tbody');
    const categoryRuns = new Map();
    for (let index = 0; index < rows.length; index += 1) {
      const item = rows[index];
      const category = String(item?.category ?? 'N/A');
      const previous = rows[index - 1];
      const startsCategoryRun = index === 0
        || String(previous?.category ?? 'N/A') !== category;
      if (!startsCategoryRun) continue;
      let span = 1;
      while (index + span < rows.length
        && String(rows[index + span]?.category ?? 'N/A') === category) span += 1;
      categoryRuns.set(index, {category, span});
    }
    rows.forEach((item, index) => {
      const row = document.createElement('tr');
      if (item?.row_type === 'category') {
        row.classList.add('scoring-category-subtotal');
        row.style.fontWeight = '700';
      }
      for (const [value, key] of [[item.category, 'category'], [item.kpi || item.kpi_code, 'kpi'], [item.kpi_type, 'type'], [item.gap_points, 'gap']]) {
        if (key === 'category') {
          const categoryRun = categoryRuns.get(index);
          if (!categoryRun) continue;
          const cell = document.createElement('td');
          cell.dataset.column = 'category';
          cell.rowSpan = categoryRun.span;
          cell.textContent = categoryRun.category;
          row.append(cell);
          continue;
        }
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
          styleIncompleteValue(cell);
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
    });
    applyGapCategoryRunColors(tbody);
    table.append(thead, tbody);
    appendGapTotals(table, rows, [null]);
    wrapper.append(table);
    pane.append(wrapper);
    observeScoringValueCells(table, wrapper);
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
    const comparisonStateKey = gapComparisonIdentity(selected, `gap-summary:${baselineRaw}`);
    let comparison = gapComparisonSelections.get(comparisonStateKey) || 'all';
    const selectedOperator = comparison.startsWith('operator:') ? comparison.slice('operator:'.length) : null;
    if (selectedOperator && !operators.includes(selectedOperator)) comparison = 'all';
    gapComparisonSelections.set(comparisonStateKey, comparison);

    const controls = document.createElement('div');
    controls.className = 'scoring-comparison-controls scoring-gap-comparison-controls';
    const label = document.createElement('label');
    label.textContent = 'GAP comparison';
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
    gapNote.textContent = `KPI GAP = compared operator weighted points minus ${baseline} weighted points for each KPI.`;
    const gapInfo = document.createElement('div');
    gapInfo.className = 'scoring-gap-info';
    gapInfo.append(gapNote);
    pane.append(gapInfo);

    const comparisons = comparison === 'all'
      ? operators
      : operators.filter(operator => `operator:${operator}` === comparison);
    const sortByGap = comparison !== 'all';
    const rows = orderGapRows(Array.isArray(selected.rows) ? selected.rows : [],
      item => comparisons.map(operator => firstValue(item?.gaps || {}, [operator], null)), sortByGap);
    appendGapScaleAside(gapInfo, selected, rows, comparison !== 'all');
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
      th.style.setProperty('--operator-text', categoryLegendTextColor(presentation.color));
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
      const previous = rows[index - 1];
      const startsCategoryRun = index === 0
        || String(previous?.category ?? '') !== category;
      if (startsCategoryRun) {
        let span = 1;
        while (index + span < rows.length
          && String(rows[index + span]?.category ?? '') === category) span += 1;
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
    applyGapCategoryRunColors(tbody);
    table.append(thead, tbody);
    appendGapTotals(table, rows, comparisons);

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

  function fittedSvgLabelLines(value, maxLength, maxLines = 2) {
    // Identifiers such as UK_Q2_SA_2026 have no spaces: also break after "_", "-" and "/", and shorten what
    // still does not fit so a label never runs into the neighbouring cells.
    const tokens = String(value).match(/\s+|[^\s_\-/]+[_\-/]*|[_\-/]+/g) || [];
    const lines = [];
    let current = '';
    for (const token of tokens) {
      if (/^\s+$/.test(token)) {
        if (current) current += ' ';
        continue;
      }
      if (current && `${current}${token}`.trimEnd().length > maxLength) {
        lines.push(current);
        current = '';
      }
      current += token;
    }
    if (current.trim()) lines.push(current);
    if (lines.length > maxLines) lines.splice(maxLines - 1, lines.length, lines.slice(maxLines - 1).join(''));
    return lines.map(line => line.trimEnd()).map(line => (
      line.length > maxLength ? `${line.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…` : line));
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

  function formatChartNumber(value, options = {}) {
    return Number(value).toLocaleString('en-US', {useGrouping: false, ...options});
  }

  function formattedChartPoints(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? formatChartNumber(numeric, {maximumFractionDigits: 3}) : 'N/A';
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

  function stackedSegmentLabelSize(label, width, height) {
    const size = Math.floor(Math.min(22, (width - 8) / (label.length * .68), (height - 5) / 1.2));
    return size >= 10 ? size : 0;
  }

  function scoringChartScale(configuredMax, actualMax) {
    const rawTarget = Math.max(0, Number(configuredMax) || 0, Number(actualMax) || 0);
    const nearestInteger = Math.round(rawTarget);
    const target = Math.abs(rawTarget - nearestInteger) <= 1e-9 * Math.max(1, rawTarget)
      ? nearestInteger : rawTarget;
    if (!target) return {maximum: 5, intervals: 5};
    const exact = [];
    if (Number.isInteger(target)) {
      for (let intervals = 3; intervals <= 6; intervals += 1) {
        if (target % intervals !== 0) continue;
        const step = target / intervals;
        const trailingZeros = (String(step).match(/0*$/) || [''])[0].length;
        exact.push({maximum: target, intervals, trailingZeros});
      }
    }
    if (exact.length) {
      exact.sort((left, right) => right.trailingZeros - left.trailingZeros
        || Math.abs(left.intervals - 5) - Math.abs(right.intervals - 5));
      return exact[0];
    }
    const unit = 10 ** Math.max(0, Math.floor(Math.log10(target / 5)) - 1);
    const candidates = Array.from({length: 4}, (_, index) => {
      const intervals = index + 3;
      const step = Math.ceil(target / intervals / unit) * unit;
      return {maximum: step * intervals, intervals};
    });
    candidates.sort((left, right) => left.maximum - right.maximum
      || Math.abs(left.intervals - 5) - Math.abs(right.intervals - 5));
    return candidates[0];
  }

  function configuredChartMaximum(tableData) {
    return (Array.isArray(tableData?.rows) ? tableData.rows : []).reduce((sum, row) => {
      const points = Number(row?.max_points);
      return sum + (Number.isFinite(points) ? points : 0);
    }, 0);
  }

  function bestNetworkHorizontalGeometry(count, groupTransitions = 0, groupGap = 0) {
    const left = 110, right = 36;
    const width = Math.max(980, count * 85 + 128 + groupTransitions * groupGap);
    const step = Math.max(1, (width - left - right - groupTransitions * groupGap) / Math.max(count, 1));
    return {width, left, right, step, barWidth: Math.min(120, step * .7)};
  }

  function fitBestNetworkChartWidth(svg, positions, count, width, right) {
    const visibleWidth = count > 10 ? positions[10] + right : width;
    svg.style.width = `${100 * width / visibleWidth}%`;
    svg.style.minWidth = '0';
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
    const requestedHierarchyLevels = Array.isArray(options.hierarchyLevels) ? options.hierarchyLevels.map(String) : [];
    // A level with the same value under every bar (a single campaign, for example) adds nothing to the axis;
    // the bar tooltips keep the complete hierarchy path.
    const varyingHierarchyLevels = requestedHierarchyLevels.filter((level, depth) => new Set(
      hierarchyColumns.map(column => hierarchyPathEntry(column, depth, requestedHierarchyLevels).rawValue),
    ).size > 1);
    const hierarchyLevels = varyingHierarchyLevels.length ? varyingHierarchyLevels : requestedHierarchyLevels.slice(0, 1);
    const hasHierarchyAxis = hierarchyLevels.length > 0 && hierarchyColumnsById.size > 0;
    const groupKeys = categories.map(category => String(options.groupKeyForCategory?.(category) || ''));
    const groupTransitions = stacked && hasHierarchyAxis
      ? groupKeys.slice(1).filter((key, index) => key && groupKeys[index] && key !== groupKeys[index]).length : 0;
    const categoryGroupGap = stacked && hasHierarchyAxis ? Math.max(0, Number(options.categoryGroupGap) || 14) : 0;
    const bestNetworkGeometry = stacked
      ? bestNetworkHorizontalGeometry(categories.length, groupTransitions, categoryGroupGap) : null;
    const requestedChartWidth = Number(options.fitWidth);
    const clusteredHierarchyWidth = !stacked && hasHierarchyAxis
      ? categories.length * (series.length * 84 + 28) + 138 : 0;
    const width = bestNetworkGeometry?.width || clusteredHierarchyWidth || (Number.isFinite(requestedChartWidth) && requestedChartWidth > 0
      ? Math.max(720, Math.floor(requestedChartWidth))
      : Math.max(1180, categories.length * Math.max(168, series.length * 38 + 22) + 150));
    const baseHeight = 700;
    const left = bestNetworkGeometry?.left ?? 110, right = bestNetworkGeometry?.right ?? 28;
    const baseBottom = Math.max(150, 80 + (hasHierarchyAxis ? hierarchyLevels.length * 32 : 0));
    const maxValue = stacked
      ? Math.max(0, ...categories.map(category => series.reduce((sum, seriesName) => {
        const row = rows.find(candidate => String(candidate.category) === String(category) && String(candidate.series) === seriesName);
        const value = row?.value === null || row?.value === undefined || String(row.value).trim() === '' ? Number.NaN : Number(row.value);
        return sum + (Number.isFinite(value) ? Math.max(0, value) : 0);
      }, 0)))
      : Math.max(0, ...rows.map(row => Number(row.value)).filter(Number.isFinite));
    const scale = scoringChartScale(stacked ? configuredChartMaximum(operatorTable) : 0, maxValue);
    const scaleMaximum = scale.maximum;
    const step = bestNetworkGeometry?.step ?? Math.max(1, (width - left - right) / Math.max(categories.length, 1));
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
    const axisTop = top + 36;
    const axisHeight = chartHeight - 36;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', title);
    if (stacked) fitBestNetworkChartWidth(svg, categories.map(category => categoryStarts.get(String(category))), categories.length, width, right);

    legendRows.forEach((row, rowIndex) => {
      let x = stacked ? left + Math.max(0, (width - left - right - (row.width - 22)) / 2) : left;
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

    const baselineY = axisTop + axisHeight;
    for (let tickIndex = 0; tickIndex <= scale.intervals; tickIndex += 1) {
      const value = scaleMaximum * (scale.intervals - tickIndex) / scale.intervals;
      const y = axisTop + axisHeight * tickIndex / scale.intervals;
      const grid = document.createElementNS(svg.namespaceURI, 'line');
      grid.setAttribute('x1', String(left)); grid.setAttribute('x2', String(width - right));
      grid.setAttribute('y1', String(y)); grid.setAttribute('y2', String(y));
      grid.setAttribute('stroke', tickIndex === scale.intervals ? '#aeb9bd' : '#e1e7e8');
      if (tickIndex !== scale.intervals) grid.setAttribute('stroke-dasharray', '4 5');
      const tick = document.createElementNS(svg.namespaceURI, 'text');
      tick.setAttribute('x', String(left - 12)); tick.setAttribute('y', String(y + 4));
      tick.setAttribute('text-anchor', 'end'); tick.setAttribute('class', 'scoring-chart-tick');
      tick.textContent = formatChartNumber(Math.round(value), {maximumFractionDigits: 0});
      svg.append(grid, tick);
    }
    const axisLabel = document.createElementNS(svg.namespaceURI, 'text');
    axisLabel.setAttribute('x', '22'); axisLabel.setAttribute('y', String(axisTop + axisHeight / 2));
    axisLabel.setAttribute('text-anchor', 'middle'); axisLabel.setAttribute('class', 'scoring-chart-axis-label');
    axisLabel.setAttribute('transform', `rotate(-90 22 ${axisTop + axisHeight / 2})`);
    axisLabel.textContent = options.axisLabel || 'Weighted score (points)';
    svg.append(axisLabel);
    if (stacked && hasHierarchyAxis) {
      appendHierarchyAxisBands(svg, categories, hierarchyLevels, hierarchyColumnsById, categoryStarts, step, baselineY, left, width - right);
    }

    categories.forEach((category, categoryIndex) => {
      if (stacked) {
        const barWidth = bestNetworkGeometry.barWidth;
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
          const segmentHeight = Math.max(0, numeric / scaleMaximum * axisHeight);
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
          const segmentText = formatChartNumber(numeric, {minimumFractionDigits: 1, maximumFractionDigits: 1});
          const fontSize = stackedSegmentLabelSize(segmentText, barWidth, segmentHeight);
          if (fontSize) {
            const segmentLabel = document.createElementNS(svg.namespaceURI, 'text');
            segmentLabel.setAttribute('x', String(x + barWidth / 2));
            segmentLabel.setAttribute('y', String(segmentY + segmentHeight / 2 + fontSize * .34));
            segmentLabel.setAttribute('text-anchor', 'middle');
            segmentLabel.setAttribute('class', 'scoring-best-network-segment');
            segmentLabel.style.fontSize = `${fontSize}px`;
            segmentLabel.style.fill = categoryLegendTextColor(color);
          styleIncompleteValue(segmentLabel);
            segmentLabel.textContent = segmentText;
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
          totalLabel.setAttribute('y', String(stackY - 10));
          totalLabel.setAttribute('text-anchor', 'middle');
          totalLabel.setAttribute('class', 'scoring-chart-value scoring-best-network-total');
          totalLabel.textContent = `${formatChartNumber(total, {minimumFractionDigits: 1, maximumFractionDigits: 1})}${complete ? '' : '*'}`;
          styleIncompleteValue(totalLabel);
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
      if (hasHierarchyAxis) {
        const starts = new Map(series.map((name, index) => [name, groupStart + index * slotWidth]));
        appendHierarchyAxisBands(svg, series, hierarchyLevels, hierarchyColumnsById, starts, slotWidth,
          baselineY, groupStart, groupStart + groupWidth);
      }
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
        const barHeight = Math.max(0, row.value / scaleMaximum * axisHeight);
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
        value.textContent = `${formatChartNumber(row.value, {maximumFractionDigits: Number.isInteger(row.value) ? 0 : 2})}${row.complete === false ? '*' : ''}`;
        styleIncompleteValue(value);
        setChartTooltip(value, tooltipParts.join('\n'));
        svg.append(rect, value);
      });
      }
      if (!hasHierarchyAxis || !stacked) {
        const lines = [];
        const visibleCategory = options.categoryLabels?.[category] || category;
        const fullCategory = options.categoryTooltips?.[category] || visibleCategory;
        lines.push(...wrappedSvgLabelLines(visibleCategory, stacked ? 24 : 22, stacked ? 4 : 2));
        const label = document.createElementNS(svg.namespaceURI, 'text');
        const categoryStart = categoryStarts.get(String(category)) ?? left + step * categoryIndex;
        const labelX = categoryStart + step / 2;
        label.setAttribute('x', String(labelX)); label.setAttribute('y', String(baselineY + 24 + (hasHierarchyAxis ? hierarchyLevels.length * 32 + 16 : 0)));
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
    const dimensionFields = ['campaign', 'region', 'cluster', 'city', 'vendor', 'dataset_type', 'environment'];
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
    const stackedChart = makeSvgChart(`${scoringLabel()} Scoring per Category`, stackedRows, selected.operatorTable, {
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
    stackedChart.style.minWidth = '0';
    pane.append(makeExpandableChartCard(`${scoringLabel()} Scoring per Category`, contextLabel(selected.context, {environmentPrefix: false}), stackedChart));
    const clusteredChart = makeSvgChart(`${scoringLabel()} Scoring per Category (Breakdown)`, selected.rows, selected.operatorTable, {
      legendEntries: operatorLegend,
      fitWidth: chartFitWidth(pane),
    });
    clusteredChart.style.minWidth = '0';
    clusteredChart.style.width = '100%';
    pane.append(makeExpandableChartCard(
      `${scoringLabel()} Scoring per Category (Breakdown)`, contextLabel(selected.context, {environmentPrefix: false}), clusteredChart,
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
    const chart = makeSvgChart(`${scoringLabel()} Scoring per Category`, rows, tableData, {
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
    chart.style.minWidth = '0';
    pane.append(makeExpandableChartCard(
      `${scoringLabel()} Scoring per Category`, contextLabel(tableData.context, {environmentPrefix: false}), chart,
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
    const clusteredChart = makeSvgChart(`${scoringLabel()} Scoring per Category (Breakdown)`, clusteredRows, tableData, {
      categoryOrder: kpiCategories,
      seriesOrder: columns.map(column => column.id),
      seriesStyles: clusteredSeriesStyles,
      seriesTooltips: clusteredSeriesTooltips,
      legendEntries: clusteredLegend,
      hierarchyLevels: tableData.hierarchy_levels,
      hierarchyColumns: columns,
    });
    clusteredChart.style.minWidth = '0';
    const clusteredWidth = clusteredChart.viewBox.baseVal.width;
    clusteredChart.style.width = `${100 * Math.max(clusteredWidth, chartFitWidth(pane)) / chartFitWidth(pane)}%`;
    clusteredChart.style.maxWidth = 'none';
    pane.append(makeExpandableChartCard(
      `${scoringLabel()} Scoring per Category (Breakdown)`, contextLabel(tableData.context, {environmentPrefix: false}), clusteredChart,
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
    const groupKeys = data.operators.map(operator => hierarchyColumnOperator(hierarchyColumnsById.get(operator)));
    const groupTransitions = hasHierarchyAxis
      ? groupKeys.slice(1).filter((key, index) => key && groupKeys[index] && key !== groupKeys[index]).length : 0;
    const categoryGroupGap = hasHierarchyAxis ? 14 : 0;
    const geometry = bestNetworkHorizontalGeometry(data.operators.length, groupTransitions, categoryGroupGap);
    const {width, left, right, step, barWidth} = geometry;
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
    const chartHeight = baseHeight + Math.max(0, top - 72);
    const height = chartHeight + 76;
    const bottom = Math.max(124, 32 + (hasHierarchyAxis ? hierarchyLevels.length * 32 : 0));
    const plotHeight = baseHeight - 72 - bottom;
    const maxAllocation = data.allocation.Voice + data.allocation.Data;
    const maxActual = Math.max(0, ...data.operators.map(operator => ['Voice', 'Data'].reduce((sum, kind) => sum + (data.totals[operator][kind].value ?? 0), 0)));
    const scale = scoringChartScale(maxAllocation, maxActual);
    const scaleMaximum = scale.maximum;
    const axisTop = top + 36;
    const axisHeight = plotHeight - 36;
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
    fitBestNetworkChartWidth(svg, data.operators.map(operator => categoryStarts.get(operator)), data.operators.length, width, right);
    svg.style.maxWidth = 'none';
    svg.style.minHeight = '0';
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${scoringLabel()} Scoring per Service`);
    if (operatorLegendRows.length) {
      operatorLegendRows.forEach((row, rowIndex) => {
        let x = left + Math.max(0, (width - left - right - (row.width - 22)) / 2);
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
    const baselineY = axisTop + axisHeight;
    for (let tickIndex = 0; tickIndex <= scale.intervals; tickIndex += 1) {
      const value = scaleMaximum * (scale.intervals - tickIndex) / scale.intervals;
      const y = axisTop + axisHeight * tickIndex / scale.intervals;
      svg.append(svgElement(svg, 'line', {x1: left, x2: width - right, y1: y, y2: y, stroke: tickIndex === scale.intervals ? '#aeb9bd' : '#e1e7e8', ...(tickIndex === scale.intervals ? {} : {'stroke-dasharray': '4 5'})}));
      const tick = svgElement(svg, 'text', {x: left - 12, y: y + 4, 'text-anchor': 'end', class: 'scoring-chart-tick'});
      tick.textContent = formatChartNumber(Math.round(value), {maximumFractionDigits: 0});
      svg.append(tick);
    }
    const axis = svgElement(svg, 'text', {x: 22, y: axisTop + axisHeight / 2, 'text-anchor': 'middle', class: 'scoring-chart-axis-label', transform: `rotate(-90 22 ${axisTop + axisHeight / 2})`});
    axis.textContent = 'Weighted score (points)';
    svg.append(axis);
    if (hasHierarchyAxis) {
      appendHierarchyAxisBands(svg, data.operators, hierarchyLevels, hierarchyColumnsById, categoryStarts, step, baselineY, left, width - right);
    }
    data.operators.forEach((operator, index) => {
      const presentation = barColors.get(operator);
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
        const segmentHeight = Math.max(0, cell.value / scaleMaximum * axisHeight);
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
        const segmentText = `${formatChartNumber(cell.value, {minimumFractionDigits: 1, maximumFractionDigits: 1})}${cell.complete ? '' : '*'}`;
        const fontSize = stackedSegmentLabelSize(segmentText, barWidth, segmentHeight);
        if (fontSize) {
          const segmentLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: segmentY + segmentHeight / 2 + fontSize * .34, 'text-anchor': 'middle', class: 'scoring-best-network-segment'});
          segmentLabel.textContent = segmentText;
          segmentLabel.style.fontSize = `${fontSize}px`;
          segmentLabel.style.fill = categoryLegendTextColor(color);
          styleIncompleteValue(segmentLabel);
          setChartTooltip(segmentLabel, segmentTooltip);
          svg.append(segmentLabel);
        }
        stackY = segmentY;
      }
      const totalLabel = svgElement(svg, 'text', {x: x + barWidth / 2, y: stackY - 12, 'text-anchor': 'middle', class: 'scoring-chart-value scoring-best-network-total'});
      totalLabel.textContent = hasPoints ? `${formatChartNumber(totalPoints, {minimumFractionDigits: 1, maximumFractionDigits: 1})}${complete ? '' : '*'}` : 'N/A';
      styleIncompleteValue(totalLabel);
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
    svg.append(svgElement(svg, 'line', {x1: left, x2: width - right, y1: chartHeight + 3, y2: chartHeight + 3, stroke: '#d6dddf', 'stroke-width': 1}));
    const serviceLegendTitle = svgElement(svg, 'text', {x: left, y: chartHeight + 17, class: 'scoring-chart-category-legend-title'});
    serviceLegendTitle.textContent = 'Service types';
    svg.append(serviceLegendTitle);
    const bandWidth = width - left - right;
    for (const [index, label, color] of [[0, 'Data', '#555555'], [1, 'Voice', '#c5c5c5']]) {
      const segmentWidth = bandWidth / 2;
      const segment = svgElement(svg, 'rect', {x: left + index * segmentWidth, y: chartHeight + 25, width: segmentWidth, height: 40, fill: color, stroke: '#ffffff', 'stroke-width': 1});
      const text = svgElement(svg, 'text', {x: left + (index + .5) * segmentWidth, y: chartHeight + 50, 'text-anchor': 'middle', class: 'scoring-chart-category-legend-label'});
      text.textContent = label;
      text.style.fill = categoryLegendTextColor(color);
      svg.append(segment, text);
    }
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
    const palette = ['#176E77', '#E6A81D', '#C55A11', '#5B9BD5', '#A64D79'];
    const allocations = [...environments.values()].map((item, index) => ({...item, color: palette[index % palette.length]}))
      .filter(item => combined || item.name.toLowerCase() === requested.toLowerCase());
    if (!allocations.length) return [{name: requested, ...bestNetworkTotals(tableData).allocation, color: palette[0]}];
    // Environments without results in any series give their points to the others,
    // in proportion, as the Combined scores do; the configured points stay visible.
    const results = typeof currentResults === 'undefined' ? null : activeScoringPayload(currentResults);
    const scaled = new Set(combined ? results?.environment_scaling?.scaled_environments || [] : []);
    const total = allocations.reduce((sum, item) => sum + item.Voice + item.Data, 0);
    const kept = allocations.filter(item => !scaled.has(item.name)).reduce((sum, item) => sum + item.Voice + item.Data, 0);
    if (!scaled.size || !(kept > 0)) return allocations;
    return allocations.map(item => {
      const factor = scaled.has(item.name) ? 0 : total / kept;
      return {...item, factor, original: {Voice: item.Voice, Data: item.Data}, Voice: item.Voice * factor, Data: item.Data * factor};
    });
  }

  function maximumAllocationCategories(tableData, environments, configuration = {}) {
    const totals = new Map();
    const originals = new Map();
    for (const metric of configuration.metrics || []) {
      const category = String(metric.category || 'Other');
      let original = 0;
      const points = environments.reduce((sum, environment) => {
        const value = Number(metric?.contexts?.[environment.name]?.max_points);
        const configured = Number.isFinite(value) && value > 0 ? value : 0;
        original += configured;
        return sum + configured * (environment.factor ?? 1);
      }, 0);
      if (original > 0) {
        totals.set(category, (totals.get(category) || 0) + points);
        originals.set(category, (originals.get(category) || 0) + original);
      }
    }
    if (!totals.size) {
      for (const row of tableData?.rows || []) {
        if (row.row_type === 'category') continue;
        const points = Number(row.max_points);
        const category = String(row.category || 'Other');
        if (Number.isFinite(points) && points > 0) totals.set(category, (totals.get(category) || 0) + points);
      }
    }
    const palette = ['#4472C4', '#7030A0', '#C55A11', '#5B9BD5', '#A64D79', '#548235', '#D65F8D', '#8064A2'];
    return [...totals].map(([label, value], index) => ({label, value, original: originals.get(label), color: palette[index % palette.length]}));
  }

  function allocationIconPath(kind) {
    if (/whatsapp/i.test(kind)) return 'M3 4h18v13H9l-6 4ZM8 7h3l1 3-2 1 3 3 1-2 3 1v3c-4 1-10-5-9-9Z';
    if (/classic|calls/i.test(kind)) return 'M6 3h4l2 5-3 2c2 4 3 5 7 7l2-3 5 2v4c-1 3-5 2-8 0C7 16 2 7 6 3Z';
    if (/multi.*rab/i.test(kind)) return 'M12 3v18M5 21l7-18 7 18M4 7a11 11 0 0 1 16 0M7 10a7 7 0 0 1 10 0';
    if (/transfer/i.test(kind)) return 'M7 3v17m-4-4 4 4 4-4M17 21V4m-4 4 4-4 4 4';
    if (/brows/i.test(kind)) return 'M2 4h20v16H2ZM2 8h20M5 6h1m2 0h1m2 0h1M8 12l-3 2 3 2m8-4 3 2-3 2';
    if (/video/i.test(kind)) return 'M3 4h18v16H3ZM9 8l7 4-7 4Z';
    if (/interactivity/i.test(kind)) return 'M2 12h4l3-8 5 16 3-8h5';
    if (kind === 'Category') return 'M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z';
    if (kind === 'Voice') return 'M6 3h4l2 5-3 2c2 4 3 5 7 7l2-3 5 2v4c-1 3-5 2-8 0C7 16 2 7 6 3Z';
    if (kind === 'Data') return 'M7 3h10v18H7ZM10 7h10m-3-3 3 3-3 3M14 16H4m3-3-3 3 3 3';
    if (/city/i.test(kind)) return 'M3 21V7h7v14M10 21V3h10v18M1 21h22M6 10v2m0 3v2m8-10h3m-3 4h3m-3 4h3';
    if (/road/i.test(kind)) return 'M5 21 9 3m10 18L15 3M12 3v3m0 3v3m0 3v3m0 2v1';
    return 'M12 22s8-8 8-13a8 8 0 0 0-16 0c0 5 8 13 8 13ZM12 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z';
  }

  function allocationEnvironmentLabel(name) {
    const savedLabel = typeof currentResults === 'undefined' ? null
      : currentResults?.configuration?.scope?.environments?.[name]?.display_name;
    if (savedLabel) return String(savedLabel);
    const normalized = String(name).replace(/[\s_-]/g, '').toLowerCase();
    if (normalized === 'drivecity') return 'Drive - City';
    if (['driveroad', 'driveconnectionroad', 'driveconnectingroads'].includes(normalized)) return 'Drive - Connecting Roads';
    return String(name);
  }

  function allocationCategoryLabel(name) {
    return String(name).toLowerCase().replace(/\b[a-z]/g, letter => letter.toUpperCase());
  }

  function allocationSectorPath(cx, cy, outerRadius, innerRadius, startAngle, endAngle) {
    const point = (radius, angle) => [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
    const span = endAngle - startAngle;
    const [ox, oy] = point(outerRadius, startAngle);
    const [ix, iy] = point(innerRadius, startAngle);
    if (span >= Math.PI * 2 - .000001) {
      const [omx, omy] = point(outerRadius, startAngle + Math.PI);
      const [imx, imy] = point(innerRadius, startAngle + Math.PI);
      return `M ${ox} ${oy} A ${outerRadius} ${outerRadius} 0 1 1 ${omx} ${omy} A ${outerRadius} ${outerRadius} 0 1 1 ${ox} ${oy} L ${ix} ${iy} A ${innerRadius} ${innerRadius} 0 1 0 ${imx} ${imy} A ${innerRadius} ${innerRadius} 0 1 0 ${ix} ${iy} Z`;
    }
    const [ex, ey] = point(outerRadius, endAngle);
    const [iex, iey] = point(innerRadius, endAngle);
    const largeArc = span > Math.PI ? 1 : 0;
    return `M ${ox} ${oy} A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${ex} ${ey} L ${iex} ${iey} A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${ix} ${iy} Z`;
  }

  function makeMaximumAllocationDonut(environments, categories = null) {
    const voiceColor = '#4472C4';
    const dataColor = '#7030A0';
    const combined = environments.length > 1;
    const total = environments.reduce((sum, item) => sum + item.Voice + item.Data, 0);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const voiceTotal = environments.reduce((sum, item) => sum + item.Voice, 0);
    const dataTotal = environments.reduce((sum, item) => sum + item.Data, 0);
    const legendItems = [];
    const addLegend = (label, color, value, iconKind, global = false, original = value) => {
      const percentage = total > 0 ? value / total * 100 : 0;
      const amount = `${formattedChartPoints(value)} pts (${percentage.toFixed(1)}%)`;
      // Points moved by scaling show the configured points struck through before them.
      const struck = Number.isFinite(original) && Math.abs(original - value) > .005 ? `${formattedChartPoints(original)} pts` : '';
      const text = `${label}: ${struck ? `${struck} ` : ''}${amount}`;
      legendItems.push({color, iconKind, global, label, amount, struck, lines: [text],
        fontSize: Math.min(14, 304 / Math.max(1, text.length * .55))});
    };
    const originalOf = (item, key) => (item.original ? item.original[key] : item[key]);
    if (combined) addLegend('Total Points', '#465565', total, 'Global', true);
    legendItems.push({heading: 'Points per Environment:'});
    environments.forEach(item => addLegend(allocationEnvironmentLabel(item.name), item.color, item.Voice + item.Data, item.name,
      false, originalOf(item, 'Voice') + originalOf(item, 'Data')));
    legendItems.push({heading: categories ? 'Points per KPI Category:' : 'Points per Service:'});
    if (categories) categories.forEach(item => addLegend(allocationCategoryLabel(item.label), item.color, item.value, item.label, false, item.original ?? item.value));
    else {
      addLegend('Voice', voiceColor, voiceTotal, 'Voice', false, environments.reduce((sum, item) => sum + originalOf(item, 'Voice'), 0));
      addLegend('Data', dataColor, dataTotal, 'Data', false, environments.reduce((sum, item) => sum + originalOf(item, 'Data'), 0));
    }
    const height = 480 + legendItems.reduce((sum, item) => sum + (item.heading ? 30 : item.lines.length * 22 + 8), 0) + 18;
    svg.setAttribute('viewBox', `0 0 460 ${height}`);
    svg.setAttribute('class', 'scoring-chart-svg scoring-allocation-donut');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', categories ? 'Maximum score by environment and category'
      : 'Maximum score by environment, Voice and Data');
    const cx = 230;
    const cy = 230;
    const outerRadius = 156;
    const outerHoleRadius = outerRadius * .72;
    const ringGap = 2;
    const innerOuterRadius = outerHoleRadius - ringGap;
    const innerHoleRadius = innerOuterRadius - outerHoleRadius * (1 - .63);
    const ringBounds = [
      {outer: outerRadius, inner: outerHoleRadius},
      {outer: innerOuterRadius, inner: innerHoleRadius},
    ];
    const familyRing = {name: categories ? 'KPI categories' : combined ? 'Global Voice/Data' : environments[0].name, segments: categories || [
      {label: 'Voice', value: voiceTotal, color: voiceColor},
      {label: 'Data', value: dataTotal, color: dataColor},
    ]};
    const rings = [{name: 'Environments', segments: environments.map(item => ({
      label: item.name, value: item.Voice + item.Data, color: item.color,
    }))}, familyRing];
    rings.forEach((ring, index) => {
      const {outer, inner} = ringBounds[index];
      const radius = (outer + inner) / 2;
      const ringTotal = ring.segments.reduce((sum, segment) => sum + segment.value, 0);
      let angle = -Math.PI / 2;
      ring.segments.forEach(segment => {
        const span = ringTotal > 0 ? Math.PI * 2 * segment.value / ringTotal : 0;
        if (span <= 0) return;
        const mark = svgElement(svg, 'path', {
          d: allocationSectorPath(cx, cy, outer, inner, angle, angle + span),
          fill: segment.color, stroke: 'none', 'data-allocation-segment': ring.name,
          'data-allocation-radius': radius, 'data-allocation-center': `${cx},${cy}`,
        });
        setChartTooltip(mark, `${ring.name}: ${segment.label}\nMaximum points: ${formattedChartPoints(segment.value)}\nShare of configured maximum: ${(ringTotal > 0 ? segment.value / ringTotal * 100 : 0).toFixed(1)}%`, true);
        svg.append(mark);
        if (index === 0) {
          const middle = angle + span / 2;
          const iconSize = 42;
          const iconRadius = outerRadius + 12 + iconSize / 2;
          const iconX = cx + iconRadius * Math.cos(middle);
          const iconY = cy + iconRadius * Math.sin(middle);
          const icon = svgElement(svg, 'path', {
            d: allocationIconPath(segment.label), fill: 'none', stroke: segment.color,
            'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
            transform: `translate(${iconX - iconSize / 2} ${iconY - iconSize / 2}) scale(${iconSize / 24})`,
            'data-allocation-environment-icon': segment.label,
          });
          setChartTooltip(icon, `Environment: ${allocationEnvironmentLabel(segment.label)}\nMaximum points: ${formattedChartPoints(segment.value)}`, true);
          svg.append(icon);
        }
        const percentage = segment.value / ringTotal * 100;
        const percentageLabel = `${percentage.toFixed(1)}%`;
        const middle = angle + span / 2;
        const centerX = radius * Math.cos(middle);
        const centerY = radius * Math.sin(middle);
        const fontSize = [14, 13, 12, 11].find((size) => {
          const halfWidth = percentageLabel.length * size * .65 / 2;
          const halfHeight = size * .6;
          const nearestRadius = Math.hypot(Math.max(Math.abs(centerX) - halfWidth, 0),
            Math.max(Math.abs(centerY) - halfHeight, 0));
          return nearestRadius >= inner + 2
            && [-halfWidth, halfWidth].every((dx) => [-halfHeight, halfHeight].every((dy) => {
            const cornerX = centerX + dx;
            const cornerY = centerY + dy;
            const cornerRadius = Math.hypot(cornerX, cornerY);
            const angleOffset = Math.atan2(Math.sin(Math.atan2(cornerY, cornerX) - middle),
              Math.cos(Math.atan2(cornerY, cornerX) - middle));
            return cornerRadius >= inner + 2 && cornerRadius <= outer - 2
              && Math.abs(angleOffset) <= span / 2 - 2 / radius;
          }));
        });
        if (fontSize) {
          const label = svgElement(svg, 'text', {
            x: cx + radius * Math.cos(middle), y: cy + radius * Math.sin(middle),
            'text-anchor': 'middle', 'dominant-baseline': 'central',
            style: `font-size:${fontSize}px;font-weight:700;fill:${readableTextColor(segment.color)}`,
            'data-allocation-percentage': percentageLabel,
          });
          label.textContent = percentageLabel;
          setChartTooltip(label, `${ring.name}: ${segment.label}\n${percentageLabel} of configured maximum`);
          svg.append(label);
        }
        angle += span;
      });
    });
    const center = svgElement(svg, 'text', {x: cx, y: cy - 4, 'text-anchor': 'middle', class: 'scoring-allocation-total'});
    center.textContent = formatChartNumber(total, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const innerRadius = innerHoleRadius;
    center.setAttribute('style', `font-size:${Math.min(31, (innerRadius * 2 - 12) / (center.textContent.length * .65))}px`);
    const unit = svgElement(svg, 'text', {x: cx, y: cy + 20, 'text-anchor': 'middle', class: 'scoring-allocation-unit'});
    unit.textContent = 'max points';
    setChartTooltip(center, `Total configured maximum\nMaximum points: ${formattedChartPoints(total)}`);
    svg.append(center, unit);
    let legendY = 480;
    legendItems.forEach(item => {
      if (item.heading) {
        const heading = svgElement(svg, 'text', {x: 18, y: legendY, style: 'font-size:14px;font-weight:700'});
        heading.textContent = item.heading;
        svg.append(heading);
        legendY += 30;
        return;
      }
      const indent = item.global ? 0 : 20;
      const icon = svgElement(svg, 'path', {d: allocationIconPath(item.iconKind), fill: 'none', stroke: item.color,
        'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
        transform: `translate(${18 + indent} ${legendY - 18}) scale(.85)`});
      const swatch = svgElement(svg, 'rect', {x: 48 + indent, y: legendY - 13, width: 14, height: 14, rx: 2, fill: item.color});
      const text = svgElement(svg, 'text', {x: 74 + indent, y: legendY,
        style: `font-size:${item.fontSize}px;font-weight:${item.global ? 700 : 400}`});
      const label = svgElement(svg, 'tspan');
      label.textContent = `${item.label}: `;
      const amount = svgElement(svg, 'tspan', {dx: 3, fill: '#8A3D0A', style: 'fill:#8A3D0A'});
      amount.textContent = item.amount;
      text.append(label);
      if (item.struck) {
        const struck = svgElement(svg, 'tspan', {dx: 3, fill: '#7A8691', 'text-decoration': 'line-through', style: 'fill:#7A8691;text-decoration:line-through'});
        struck.textContent = item.struck;
        text.append(struck);
      }
      text.append(amount);
      setChartTooltip(text, item.lines.join(' '));
      svg.append(icon, swatch, text);
      legendY += item.lines.length * 22 + 8;
    });
    return svg;
  }

  function renderCategoryAllocation(pane, scoreTables, hierarchyTable, allTables) {
    const card = pane.querySelector(':scope > .scoring-chart-card');
    const selected = hierarchyTable
      || scoreTables.find(table => comparisonIdentity(table, 'score') === contextSelections.get('score'))
      || scoreTables[0];
    if (!card || !selected) return;
    const configuration = activeScoringConfiguration();
    const allocations = maximumAllocationEnvironments(selected, allTables, configuration);
    const categories = maximumAllocationCategories(selected, allocations, configuration);
    if (!categories.length) return;
    const layout = document.createElement('div');
    layout.className = 'scoring-best-network-layout';
    pane.insertBefore(layout, card);
    layout.append(card, makeExpandableChartCard('Maximum score per environment & category',
      contextLabel(selected.context, {environmentPrefix: false}), makeMaximumAllocationDonut(allocations, categories)));
  }

  function renderBestNetworkChart(pane, scoreTables, hierarchyTable = null, allTables = scoreTables) {
    if (!hierarchyTable && !scoreTables.length) {
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = `No ${scoringLabel()} chart is available for this environment.`;
      pane.append(empty);
      return;
    }
    const selected = hierarchyTable
      || scoreTables.find(table => comparisonIdentity(table, 'score') === contextSelections.get('score'))
      || scoreTables[0];
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
    const meta = contextLabel(selected.context, {environmentPrefix: false});
    const bars = makeBestNetworkBars(selected, data);
    layout.append(makeExpandableChartCard(`${scoringLabel()} Scoring per Service`, meta, bars));
    const configuration = activeScoringConfiguration();
    const allocations = maximumAllocationEnvironments(selected, allTables, configuration);
    const donut = makeMaximumAllocationDonut(allocations);
    layout.append(makeExpandableChartCard('Maximum score per environment & service', meta, donut));
    pane.insertBefore(layout, pane.querySelector(':scope > .scoring-best-network-layout, :scope > .scoring-chart-card'));
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

  // Information about the calculation, such as environments scaled to the maximum scoring.
  // NetCheck-style insights of the selected scoring: location cards, scoring trends,
  // KPI GAP profiles and campaign comparisons, as in the PowerPoint and Word exports.
  const insightVoiceColor = '#F2A900';
  const insightDataColor = '#0E6B66';
  const insightFallbackColors = ['#E60000', '#0B6E8F', '#7A3DB8', '#00A3AD', '#F2A900', '#4CA65A', '#8C564B', '#5B6770'];
  const insightSelections = new Map();

  function insightItems(payload, kind, environment) {
    const items = payload?.views?.insights?.[kind];
    return (Array.isArray(items) ? items : []).filter(item => item?.environment === environment);
  }

  function insightNumber(value, digits = 0) {
    return Number.isFinite(Number(value)) && value !== null
      ? Number(value).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : 'N/A';
  }

  // Chronological order; in a quarter, the plain campaign first, then NSA, then SA.
  function insightCampaignKey(value) {
    if (typeof globalThis.campaignSortKey === 'function') {
      const [year, quarter, rank, exception] = globalThis.campaignSortKey(value);
      return year < 0 ? exception - 1e6 : year * 100000 + quarter * 10000 + rank * 100 + exception;
    }
    const match = hierarchyDisplayValue({level: 'Campaign', value}).match(/^((?:19|20)\d{2})-Q([1-4])(?:-(NSA|SA))?$/);
    return match ? Number(match[1]) * 100 + Number(match[2]) * 10 + ({NSA: 1, SA: 2}[match[3]] || 0) : Number.NEGATIVE_INFINITY;
  }

  function shortOperatorLabel(label) {
    const first = String(label || '').replace(/_/g, ' ').trim().split(/\s+/)[0] || String(label || '');
    return first.length <= 5 ? first : first.slice(0, 3);
  }

  function insightContextLabel(context) {
    const names = {vendor: 'Vendor', region: 'Region', cluster: 'Cluster', city: 'City', campaign: 'Campaign'};
    return Object.entries(names).filter(([field]) => context?.[field] !== undefined && context?.[field] !== null && context?.[field] !== '')
      .map(([field, label]) => `${label}: ${field === 'campaign' ? hierarchyDisplayValue({level: 'Campaign', value: context[field]}) : context[field]}`)
      .join(' · ');
  }

  function insightSelect(key, options, label) {
    const wrapper = document.createElement('label');
    wrapper.className = 'scoring-environment-filter scoring-insight-select';
    wrapper.append(document.createTextNode(label));
    const select = document.createElement('select');
    select.dataset.insightSelect = key;
    for (const [value, text] of options) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      select.append(option);
    }
    const stored = insightSelections.get(key);
    select.value = options.some(([value]) => value === stored) ? stored : options[0]?.[0] ?? '';
    wrapper.append(select);
    return {wrapper, value: select.value};
  }

  function makeLocationCardChart(card, maximum) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const operators = card.operators || [];
    const width = Math.max(190, operators.length * 48 + 20), height = 230;
    const top = 26, bottom = 30, plotHeight = height - top - bottom;
    const scale = value => (Number(value) || 0) / (Number(maximum) || 1) * plotHeight * .9;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-location-card-chart');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${card.label}: ${operators.map(item => `${item.label} ${insightNumber(item.total)}`).join(', ')}`);
    const step = (width - 20) / Math.max(1, operators.length);
    const barWidth = Math.min(34, step * .62);
    operators.forEach((item, index) => {
      const x = 10 + step * index + (step - barWidth) / 2;
      const voiceHeight = scale(item.voice), dataHeight = scale(item.data);
      const baseline = top + plotHeight;
      const group = svgElement(svg, 'g');
      setChartTooltip(group, `${item.label}: ${insightNumber(item.total, 1)} points (Voice ${insightNumber(item.voice, 1)}, Data ${insightNumber(item.data, 1)})${item.complete ? '' : ' — incomplete coverage'}`, true);
      group.append(svgElement(svg, 'rect', {x, y: baseline - voiceHeight, width: barWidth, height: voiceHeight, fill: insightVoiceColor}));
      group.append(svgElement(svg, 'rect', {x, y: baseline - voiceHeight - dataHeight, width: barWidth, height: dataHeight, fill: insightDataColor}));
      for (const [value, y, size] of [[item.voice, baseline - voiceHeight / 2, 10], [item.data, baseline - voiceHeight - dataHeight / 2, 10]]) {
        if (scale(value) < 14) continue;
        const text = svgElement(svg, 'text', {x: x + barWidth / 2, y: y + 3.5, 'text-anchor': 'middle', 'font-size': size, fill: '#ffffff'});
        text.textContent = insightNumber(value);
        group.append(text);
      }
      const total = svgElement(svg, 'text', {x: x + barWidth / 2, y: baseline - voiceHeight - dataHeight - 6, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 800, fill: '#17232d'});
      total.textContent = `${insightNumber(item.total)}${item.complete ? '' : '*'}`;
      const label = svgElement(svg, 'text', {x: x + barWidth / 2, y: baseline + 18, 'text-anchor': 'middle', 'font-size': 12, fill: '#4a5b65'});
      label.textContent = shortOperatorLabel(item.label);
      group.append(total, label);
      svg.append(group);
    });
    svg.append(svgElement(svg, 'line', {x1: 4, x2: width - 4, y1: top + plotHeight, y2: top + plotHeight, stroke: '#bfc6cc'}));
    return svg;
  }

  function makeLocationCardsView(group) {
    const layout = document.createElement('div');
    layout.className = 'scoring-location-cards';
    const panel = document.createElement('div');
    panel.className = 'scoring-location-panel';
    const plural = {City: 'cities', Cluster: 'clusters', Region: 'regions'}[group.level] || 'locations';
    const lines = [`The ${scoringLabel()} scoring per ${String(group.level).toLowerCase()} for the selected ${plural}.`];
    if (group.scaled) lines.push(`The scoring points are scaled to a maximum of ${insightNumber(group.maximum)} points, providing comparability with the overall scoring.`);
    for (const line of lines) {
      const paragraph = document.createElement('p');
      paragraph.textContent = line;
      panel.append(paragraph);
    }
    const total = document.createElement('strong');
    total.textContent = `Total: ${insightNumber(group.maximum)} points`;
    const split = document.createElement('span');
    split.textContent = `Voice: ${insightNumber(group.max_voice)} · Data: ${insightNumber(group.max_data)}`;
    panel.append(total, split);
    layout.append(panel);
    for (const card of group.cards || []) {
      const article = document.createElement('article');
      article.className = 'scoring-location-card';
      const heading = document.createElement('h5');
      heading.textContent = String(card.label).toUpperCase();
      article.append(heading, makeLocationCardChart(card, group.maximum));
      layout.append(article);
    }
    const legend = document.createElement('div');
    legend.className = 'scoring-location-legend';
    legend.innerHTML = `<span><i style="background:${insightVoiceColor}"></i>Voice</span><span><i style="background:${insightDataColor}"></i>Data</span>`;
    const wrapper = document.createElement('div');
    wrapper.append(layout, legend);
    return wrapper;
  }

  function makeTrendChart(trend) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const width = 980, height = 380, left = 56, right = 30, top = 22, bottom = 70;
    const values = trend.series.flatMap(series => series.points).filter(value => Number.isFinite(Number(value)) && value !== null);
    const minimum = Math.max(0, Math.floor((Math.min(...values) - 25) / 50) * 50);
    const maximum = Number(trend.maximum) || Math.max(...values);
    const x = index => left + (width - left - right) * (trend.campaigns.length > 1 ? index / (trend.campaigns.length - 1) : .5);
    const y = value => top + (height - top - bottom) * (1 - (value - minimum) / Math.max(1, maximum - minimum));
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'scoring-trend-chart');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${scoringLabel()} scoring trend`);
    const gridStep = [25, 50, 100, 200, 250].find(step => (maximum - minimum) / step <= 10) || 500;
    for (let value = minimum; value <= maximum + .001; value += gridStep) {
      svg.append(svgElement(svg, 'line', {x1: left, x2: width - right, y1: y(value), y2: y(value), stroke: '#e3e6e9'}));
      const label = svgElement(svg, 'text', {x: left - 8, y: y(value) + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#4a5b65'});
      label.textContent = insightNumber(value);
      svg.append(label);
    }
    trend.campaigns.forEach((campaign, index) => {
      const label = svgElement(svg, 'text', {x: x(index), y: height - bottom + 20, 'text-anchor': 'middle', 'font-size': 12, fill: '#263746'});
      label.textContent = campaign;
      svg.append(label);
    });
    trend.series.forEach((series, seriesIndex) => {
      const color = safeHexColor(series.color) || insightFallbackColors[seriesIndex % insightFallbackColors.length];
      const points = series.points.map((value, index) => (value === null || value === undefined ? null : [x(index), y(value), value]));
      const path = points.filter(Boolean).map(([px, py], index) => `${index ? 'L' : 'M'}${px},${py}`).join(' ');
      svg.append(svgElement(svg, 'path', {d: path, fill: 'none', stroke: color, 'stroke-width': 2.5}));
      points.forEach((point, index) => {
        if (!point) return;
        const marker = svgElement(svg, 'circle', {cx: point[0], cy: point[1], r: 4.5, fill: color});
        setChartTooltip(marker, `${series.label} · ${trend.campaigns[index]}: ${insightNumber(point[2], 1)} points`, true);
        const label = svgElement(svg, 'text', {x: point[0], y: point[1] - 9, 'text-anchor': 'middle', 'font-size': 10, fill: color, 'font-weight': 700});
        label.textContent = insightNumber(point[2]);
        svg.append(marker, label);
      });
      const legendX = left + seriesIndex * 170;
      svg.append(svgElement(svg, 'line', {x1: legendX, x2: legendX + 22, y1: height - 18, y2: height - 18, stroke: color, 'stroke-width': 3}));
      const legend = svgElement(svg, 'text', {x: legendX + 28, y: height - 14, 'font-size': 12, fill: '#263746'});
      legend.textContent = series.label;
      svg.append(legend);
    });
    return svg;
  }

  function renderInsightCharts(pane, payload, environment) {
    if (!environment) return;
    let groups = insightItems(payload, 'location_cards', environment);
    const campaigns = [...new Set(groups.map(group => group.campaign).filter(Boolean))];
    if (campaigns.length > 1) {
      const latest = campaigns.sort((left, right) => insightCampaignKey(left) - insightCampaignKey(right)).at(-1);
      groups = groups.filter(group => !group.campaign || group.campaign === latest);
    }
    for (const group of groups) {
      pane.append(makeExpandableChartCard(`${scoringLabel()} Scoring per ${group.level}`,
        [environmentLabel(environment), group.title].filter(Boolean).join(' · '), makeLocationCardsView(group)));
    }
    const trends = insightItems(payload, 'campaign_trends', environment);
    if (trends.length) {
      const {wrapper, value} = insightSelect('trend', trends.map((trend, index) => [String(index), trend.title || 'All series']), 'Series');
      const trend = trends[Number(value)] || trends[0];
      const card = makeExpandableChartCard(`${scoringLabel()} Scoring Trend`,
        [environmentLabel(environment), trend.title].filter(Boolean).join(' · '), makeTrendChart(trend));
      if (trends.length > 1) card.insertBefore(wrapper, card.children[1]);
      pane.append(card);
    }
  }

  function insightTable(headers, rows, {className = ''} = {}) {
    const table = document.createElement('table');
    table.className = `scoring-insight-table ${className}`.trim();
    const head = table.createTHead().insertRow();
    for (const header of headers) {
      const cell = document.createElement('th');
      cell.textContent = header;
      head.append(cell);
    }
    const body = table.createTBody();
    for (const cells of rows) {
      const row = body.insertRow();
      for (const content of cells) {
        const cell = row.insertCell();
        if (content instanceof Node) cell.append(content);
        else if (content && typeof content === 'object') {
          cell.textContent = content.text ?? '';
          if (content.className) cell.className = content.className;
          if (content.style) Object.assign(cell.style, content.style);
          if (content.bar) {
            // A data bar under the value: the colour fading to white, as in the NetCheck tables.
            const bar = document.createElement('span');
            bar.className = 'scoring-insight-databar';
            bar.style.width = `calc((100% - .3rem) * ${content.bar.ratio})`;
            bar.style.setProperty('--databar-color', content.bar.color);
            const text = document.createElement('span');
            text.className = 'scoring-insight-databar-value';
            text.textContent = cell.textContent;
            cell.replaceChildren(bar, text);
          }
        } else cell.textContent = content ?? '';
      }
    }
    return table;
  }

  function gapBarCell(value, scale, {loss = false, total = false} = {}) {
    const cell = {text: insightNumber(value, 2),
      className: `scoring-insight-bar-cell${total ? ' scoring-insight-total' : ''}`};
    if (value === null || value === undefined || !Number(value) || !scale) return cell;
    cell.bar = {ratio: Math.min(1, Math.abs(value) / scale), color: loss || value < 0 ? '#e8414f' : '#4ca65a'};
    return cell;
  }

  function profileTable(profile, kind) {
    const rows = kind === 'maximum' ? profile.to_maximum : profile.to_reference;
    const totalKey = kind === 'maximum' ? 'total_gap_to_maximum' : 'total_gap_to_reference';
    const valueKey = kind === 'maximum' ? 'gap_to_maximum' : 'gap_to_reference';
    // Each value column has its own bar scale.
    const columnScale = values => Math.max(0, ...values.map(value => Math.abs(Number(value) || 0)));
    const scale = columnScale(rows.map(row => row[totalKey]));
    const scales = Object.fromEntries(profile.columns.map(name => [name, columnScale(rows.map(row => row[valueKey]?.[name]))]));
    const wrapper = document.createElement('div');
    wrapper.className = 'scoring-insight-table-wrap';
    const banner = document.createElement('div');
    banner.className = 'scoring-insight-banner';
    const bannerColor = safeHexColor(profile.color);
    if (bannerColor) banner.style.background = bannerColor;
    banner.textContent = kind === 'maximum' ? `${profile.label}: Gap to Maximum` : `${profile.label}: Gap to ${profile.reference_label}`;
    wrapper.append(banner, insightTable(
      ['Service', 'Area', 'KPI', ...profile.columns.map(name => environmentLabel(name)), 'Total KPI'],
      rows.map(row => {
        const underline = profile.underline_most_reliable && row.most_reliable ? 'scoring-insight-reliable' : '';
        return [row.service.toUpperCase(), {text: row.category, className: underline}, {text: row.kpi, className: underline},
          ...profile.columns.map(name => gapBarCell(row[valueKey]?.[name], scales[name], {loss: kind === 'maximum'})),
          gapBarCell(row[totalKey], scale, {loss: kind === 'maximum', total: true})];
      }),
    ));
    return wrapper;
  }

  function renderKpiGapProfiles(pane, payload, environment) {
    if (!environment) return;
    const profiles = insightItems(payload, 'kpi_gap_profiles', environment).filter(profile => profile.operator !== profile.reference);
    if (!profiles.length) return;
    const section = document.createElement('section');
    section.className = 'scoring-insight-section';
    const heading = document.createElement('h4');
    heading.className = 'scoring-table-section-title';
    heading.textContent = 'KPI GAP Profile';
    // The profile follows the operator chosen in the GAP comparison above it, and the reverse.
    const comparisonSelect = pane.querySelector('[data-hierarchy-gap-operator], [data-gap-summary-operator]');
    const compared = comparisonSelect?.value?.startsWith('operator:') ? comparisonSelect.value.slice('operator:'.length) : null;
    const current = profiles[Number(insightSelections.get('gap-profile'))];
    if (compared && current?.operator !== compared) {
      const sameContext = profiles.findIndex(item => item.operator === compared
        && JSON.stringify(item.context) === JSON.stringify(current?.context));
      const firstMatch = profiles.findIndex(item => item.operator === compared);
      const index = sameContext >= 0 ? sameContext : firstMatch;
      if (index >= 0) insightSelections.set('gap-profile', String(index));
    }
    const {wrapper, value} = insightSelect('gap-profile', profiles.map((profile, index) => [
      String(index), [`${profile.label} vs ${profile.reference_label}`, insightContextLabel(profile.context)].filter(Boolean).join(' · '),
    ]), 'Comparison');
    const profile = profiles[Number(value)] || profiles[0];
    const tables = document.createElement('div');
    tables.className = 'scoring-insight-pair';
    tables.append(profileTable(profile, 'maximum'), profileTable(profile, 'reference'));
    const lost = profile.to_maximum.reduce((sum, row) => sum + (Number(row.total_gap_to_maximum) || 0), 0);
    const gap = profile.to_reference.reduce((sum, row) => sum + (Number(row.total_gap_to_reference) || 0), 0);
    const note = document.createElement('p');
    note.className = 'scoring-insight-note';
    note.innerHTML = '';
    const operator = document.createElement('strong');
    operator.textContent = profile.label;
    const reference = document.createElement('strong');
    reference.textContent = profile.reference_label;
    const lostText = document.createElement('strong');
    lostText.textContent = `${insightNumber(lost, 2)} ${scoringLabel()} points`;
    const gapText = document.createElement('strong');
    gapText.textContent = `${gap >= 0 ? '+' : ''}${insightNumber(gap, 2)} points`;
    note.append(operator, ' loses ', lostText, ' against the maximum; its GAP to ', reference, ' is ', gapText,
      '. Gap to Maximum is the KPI maximum minus the points scored; Gap to the reference is the operator points minus the reference points.');
    if (profile.underline_most_reliable) note.append(' Underlined KPIs are used for the Most Reliable Network scoring.');
    section.append(heading, wrapper, tables, note);
    pane.append(section);
  }

  // Points lost per area: the ITL3 areas (or the workspace Clusters and Regions) coloured
  // by the points lost, and the cities, routes or clusters that lose most.
  const lossBoundaryCache = new Map();
  const lossLow = [249, 214, 92];
  const lossHigh = [200, 16, 46];
  const maxLossBars = 30;

  function lossColor(ratio) {
    const value = Math.max(0, Math.min(1, Number(ratio) || 0));
    return `rgb(${lossLow.map((low, index) => Math.round(low + (lossHigh[index] - low) * value)).join(',')})`;
  }

  function lossBoundaries(jobId, field) {
    const key = `${jobId}:${field}`;
    if (!lossBoundaryCache.has(key)) {
      lossBoundaryCache.set(key, requestJson(`${jobsUrl}/${encodeURIComponent(jobId)}/boundaries/${encodeURIComponent(field)}`)
        .then(body => body?.boundaries || {}).catch(() => ({})));
    }
    return lossBoundaryCache.get(key);
  }

  function lossMapSvg(boundaries, values, areas, background) {
    const svgNs = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNs, 'svg');
    svg.classList.add('scoring-loss-map-svg');
    const rings = Object.entries(boundaries).flatMap(([name, polygons]) => polygons.map(ring => [name, ring]));
    const points = rings.length ? rings.flatMap(([, ring]) => ring)
      : [...background.map(([lat, lon]) => [lon, lat]), ...areas.filter(area => area.latitude !== null && area.latitude !== undefined)
        .map(area => [area.longitude, area.latitude])];
    if (!points.length) return svg;
    const xs = points.map(point => point[0]);
    const ys = points.map(point => point[1]);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const scaleX = Math.cos((minY + maxY) / 2 * Math.PI / 180);
    const height = 600;
    const unit = (maxY - minY) / (height - 20) || 1e-6;
    const width = Math.max(200, (maxX - minX) * scaleX / unit + 20);
    svg.setAttribute('viewBox', `0 0 ${width.toFixed(0)} ${height}`);
    const project = (x, y) => [10 + (x - minX) * scaleX / unit, height - 10 - (y - minY) / unit];
    const positive = Object.values(values).filter(value => value > 0);
    const low = positive.length ? Math.min(...positive) : 0;
    const span = (positive.length ? Math.max(...positive) : 0) - low || 1;
    const tooltip = (element, name, value) => {
      const title = document.createElementNS(svgNs, 'title');
      title.textContent = `${name}: ${insightNumber(value, 2)} points lost`;
      element.append(title);
    };
    if (rings.length) {
      for (const [name, ring] of rings) {
        const path = document.createElementNS(svgNs, 'path');
        path.setAttribute('d', `M${ring.map(([x, y]) => project(x, y).map(value => value.toFixed(1)).join(',')).join('L')}Z`);
        const value = values[name] || 0;
        path.setAttribute('fill', value > 0 ? lossColor((value - low) / span) : '#eaecef');
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '.6');
        tooltip(path, name, value);
        svg.append(path);
      }
      return svg;
    }
    for (const [lat, lon] of background) {
      const [x, y] = project(lon, lat);
      const dot = document.createElementNS(svgNs, 'circle');
      Object.entries({cx: x.toFixed(1), cy: y.toFixed(1), r: 1.4, fill: '#d6dce2'}).forEach(([key, value]) => dot.setAttribute(key, value));
      svg.append(dot);
    }
    const peak = Math.max(0, ...areas.map(area => area.points)) || 1;
    for (const area of [...areas].sort((a, b) => a.points - b.points)) {
      const color = lossColor(area.points / peak);
      const spots = area.kind === 'route' && area.route?.length ? area.route.map(([lat, lon]) => [lon, lat, 3])
        : area.latitude !== null && area.latitude !== undefined ? [[area.longitude, area.latitude, 4 + 16 * Math.sqrt(area.points / peak)]] : [];
      for (const [lon, lat, radius] of spots) {
        const [x, y] = project(lon, lat);
        const circle = document.createElementNS(svgNs, 'circle');
        Object.entries({cx: x.toFixed(1), cy: y.toFixed(1), r: radius.toFixed(1), fill: color, stroke: '#fff'})
          .forEach(([key, value]) => circle.setAttribute(key, value));
        tooltip(circle, area.name, area.points);
        svg.append(circle);
      }
    }
    return svg;
  }

  function renderPointsLossMaps(pane, payload, environment, jobId) {
    if (!environment || !jobId) return;
    const maps = insightItems(payload, 'points_loss_maps', environment).filter(item => !item.is_reference);
    if (!maps.length) return;
    const seriesKey = item => `${item.operator}|${JSON.stringify(item.context)}`;
    const layers = new Map(maps.filter(item => item.field === 'ITL3').map(item => [seriesKey(item), item]));
    const entries = [];
    for (const item of maps) {
      if (item.field === 'City') entries.push({ranking: item, layer: layers.get(seriesKey(item)) || null, title: 'City'});
      else if (['Cluster', 'Region'].includes(item.field)) entries.push({ranking: item, layer: item, title: item.field});
    }
    if (!entries.length) return;
    const section = document.createElement('section');
    section.className = 'scoring-insight-section';
    const heading = document.createElement('h4');
    heading.className = 'scoring-table-section-title';
    heading.textContent = 'Points Lost Map';
    // Like the KPI GAP Profile, the map follows the operator chosen in the GAP comparison.
    const comparisonSelect = pane.querySelector('[data-hierarchy-gap-operator], [data-gap-summary-operator]');
    const compared = comparisonSelect?.value?.startsWith('operator:') ? comparisonSelect.value.slice('operator:'.length) : null;
    const current = entries[Number(insightSelections.get('points-loss'))];
    if (compared && current?.ranking.operator !== compared) {
      const index = entries.findIndex(entry => entry.ranking.operator === compared && entry.title === (current?.title || 'City'));
      if (index >= 0) insightSelections.set('points-loss', String(index));
    }
    const {wrapper, value} = insightSelect('points-loss', entries.map((entry, index) => [String(index),
      [`${entry.ranking.label} per ${entry.title}`, insightContextLabel(entry.ranking.context)].filter(Boolean).join(' · ')]), 'Map');
    const entry = entries[Number(value)] || entries[0];
    const {ranking, layer} = entry;
    const bars = ranking.areas.filter(area => area.name !== 'Not specified').slice(0, maxLossBars);
    const listed = bars.reduce((sum, area) => sum + area.points, 0);
    const note = document.createElement('p');
    note.className = 'scoring-insight-note';
    const operator = document.createElement('strong');
    operator.textContent = ranking.label;
    const color = safeHexColor(ranking.color);
    if (color) operator.style.color = color;
    const listedText = document.createElement('strong');
    listedText.textContent = `The ${bars.length} ${entry.title === 'City' ? 'cities and routes' : `${entry.title.toLowerCase()}s`} listed`;
    note.append(layer && layer.field === 'ITL3' ? 'The map colours each ITL3 area by the points ' : 'The map shows where ',
      operator, ` loses its ${scoringLabel()} points (${insightNumber(ranking.total, 1)} in total). `, listedText,
      ` account for ${ranking.total ? Math.round(listed / ranking.total * 100) : 0}% of the points lost.`);
    const content = document.createElement('div');
    content.className = 'scoring-loss-map';
    const mapBox = document.createElement('div');
    mapBox.className = 'scoring-loss-map-figure';
    mapBox.textContent = 'Loading map…';
    const peak = Math.max(0, ...bars.map(area => area.points));
    const table = insightTable(['Area', 'Points lost', 'Share'], bars.map(area => [area.name,
      gapBarCell(area.points, peak, {loss: true, total: true}),
      {text: `${insightNumber(area.share * 100, 1)}%`, className: 'scoring-insight-number'}]));
    const tableBox = document.createElement('div');
    tableBox.className = 'scoring-insight-table-wrap';
    tableBox.append(table);
    content.append(mapBox, tableBox);
    section.append(heading, wrapper, note, content);
    pane.append(section);
    const values = Object.fromEntries((layer || ranking).areas.filter(area => area.name !== 'Not specified')
      .map(area => [area.name, area.points]));
    (layer ? lossBoundaries(jobId, layer.field) : Promise.resolve({})).then(boundaries => {
      const svg = lossMapSvg(layer ? boundaries : {}, values, ranking.areas, payload?.views?.insights?.points_loss_background || []);
      mapBox.replaceChildren(svg);
    });
  }

  function renderCampaignComparisons(pane, payload, environment) {
    if (!environment) return;
    const comparisons = insightItems(payload, 'campaign_comparisons', environment);
    if (!comparisons.length) return;
    const section = document.createElement('section');
    section.className = 'scoring-insight-section';
    const heading = document.createElement('h4');
    heading.className = 'scoring-table-section-title';
    heading.textContent = 'Campaign Comparison';
    const {wrapper, value} = insightSelect('campaign-comparison', comparisons.map((item, index) => [
      String(index), [item.label, item.title, `${item.previous_campaign} → ${item.latest_campaign}`].filter(Boolean).join(' · '),
    ]), 'Comparison');
    const comparison = comparisons[Number(value)] || comparisons[0];
    const scale = Math.max(0, ...comparison.rows.map(row => Math.abs(Number(row.delta) || 0)));
    const deltaCell = delta => {
      const cell = {text: insightNumber(delta, 2), className: 'scoring-insight-number scoring-insight-delta'};
      if (delta === null || delta === undefined || !scale || !delta) return cell;
      const alpha = Math.min(1, Math.abs(delta) / scale) * .75;
      cell.style = {background: delta < 0 ? `rgba(232,65,79,${alpha})` : `rgba(76,166,90,${alpha})`};
      return cell;
    };
    const table = insightTable(
      ['Service', 'KPI', `${comparison.previous_campaign} KPI value`, `${comparison.previous_campaign} Points`,
        `${comparison.latest_campaign} KPI value`, `${comparison.latest_campaign} Points`, 'Δ Points'],
      comparison.rows.map(row => [row.service.toUpperCase(), row.kpi,
        {text: insightNumber(row.previous_value, 2), className: 'scoring-insight-number'},
        {text: insightNumber(row.previous_points, 2), className: 'scoring-insight-number'},
        {text: insightNumber(row.latest_value, 2), className: 'scoring-insight-number'},
        {text: insightNumber(row.latest_points, 2), className: 'scoring-insight-number'}, deltaCell(row.delta)]),
    );
    const total = document.createElement('p');
    total.className = 'scoring-insight-total';
    const value_ = document.createElement('strong');
    value_.textContent = `${comparison.total_delta >= 0 ? '+' : ''}${insightNumber(comparison.total_delta, 2)}`;
    value_.className = comparison.total_delta < 0 ? 'scoring-insight-loss' : 'scoring-insight-gain';
    total.append('Scoring Points Gap: ', value_);
    const body = document.createElement('div');
    body.className = 'scoring-insight-compare';
    body.append(table, total);
    section.append(heading, wrapper, body);
    pane.append(section);
  }

  function renderNotices(notices) {
    const box = root.querySelector('[data-notice-box]');
    const list = root.querySelector('[data-notice-list]');
    if (!box || !list) return;
    const items = (Array.isArray(notices) ? notices : []).map(String).filter(Boolean);
    list.replaceChildren(...items.map(text => Object.assign(document.createElement('li'), {textContent: text})));
    box.hidden = !items.length;
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
      const message = typeof warning === 'string' ? warning : displayValue(warning);
      const maximumPattern = /(?:maximum achievable scoring )?[0-9]+(?:\.[0-9]+)? of [0-9]+(?:\.[0-9]+)? points/g;
      let offset = 0;
      for (const match of message.matchAll(maximumPattern)) {
        item.append(document.createTextNode(message.slice(offset, match.index)));
        const maximum = document.createElement('strong');
        maximum.className = 'scoring-warning-maximum';
        maximum.textContent = match[0];
        item.append(maximum);
        offset = match.index + match[0].length;
      }
      item.append(document.createTextNode(message.slice(offset)));
      list.append(item);
    }
  }

  const environmentOrder = ['DriveCity', 'DriveConnectionroad', 'Walk', 'Combined'];
  const comparisonScopeFields = ['campaign', 'region', 'cluster', 'city', 'vendor', 'dataset_type'];

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
    const savedLabel = typeof currentResults === 'undefined' ? null
      : currentResults?.configuration?.scope?.environments?.[environment]?.display_name;
    if (savedLabel) return String(savedLabel);
    if (environment === 'DriveCity') return 'Drive City';
    if (environment === 'DriveConnectionroad') return 'Drive Connection Road';
    if (environment === 'Walk') return 'Walk';
    return environment;
  }

  function scoringCoverageTotals(payload, environment) {
    const totals = Array.isArray(payload?.totals) ? payload.totals : [];
    const matching = totals.filter(row => String(row.environment || '') === environment && Number(row.max_points) > 0);
    const overall = matching.filter(row => row.category === 'Overall');
    return overall.length ? overall : matching;
  }

  function scoringEnvironmentIsComplete(payload, tables, environment) {
    const totals = scoringCoverageTotals(payload, environment);
    if (totals.length) return totals.every(row => row.complete_coverage === true);
    const matching = tables.filter(table => environmentOf(table) === environment
      && (table.total?.max_points === undefined || Number(table.total.max_points) > 0));
    const values = matching.flatMap(table => Object.values(table.total?.values || {}))
      .filter(cell => cell.points !== null && cell.points !== undefined);
    return values.length > 0 && values.every(cell => cell.complete === true);
  }

  function scoringCoverageWarnings(payload, job, environment, {concise = false} = {}) {
    const genericNotice = 'Incomplete KPI or environment coverage: partial points are shown without renormalizing weights; a complete benchmark score is unavailable.';
    const warnings = Array.isArray(payload?.warnings) ? payload.warnings : (payload?.warnings ? [payload.warnings] : []);
    const totals = scoringCoverageTotals(payload, environment);
    if (!totals.length) return warnings;
    const visible = warnings.filter(warning => warning !== genericNotice);
    const detailedNotes = payload?.coverage_notes?.[environment];
    if (Array.isArray(detailedNotes)) return [...visible, ...detailedNotes];
    const incomplete = totals.filter(row => row.complete_coverage === false);
    if (!incomplete.length) return visible;
    const required = Object.entries(payload.configuration?.scope?.environments || {})
      .filter(([, config]) => Number(config.total_points) > 0).map(([name]) => name);
    const missing = new Set();
    const partial = new Set();
    if (environment === 'Combined') {
      for (const total of incomplete) {
        for (const name of required) {
          const contribution = scoringCoverageTotals(payload, name).find(row => row.operator === total.operator
            && comparisonScopeFields.every(field => String(row[field] ?? '') === String(total[field] ?? '')));
          if (!contribution) missing.add(name);
          else if (contribution.complete_coverage === false) partial.add(name);
        }
      }
    }
    if (concise) {
      const label = name => ['DriveConnectionroad', 'Drive Connecting Roads'].includes(name)
        ? 'Drive - Connecting Roads' : environmentLabel(name);
      const names = [...missing].map(label);
      let message = names.length
        ? `Selected Environment has incomplete coverage because ${names.length === 1 ? 'one of its Environments' : 'some of its Environments'} (${names.join(', ')}) ${names.length === 1 ? 'has' : 'have'} no data with the selected filters.`
        : 'Selected Environment has incomplete coverage because required KPI data is missing with the selected filters.';
      if (partial.size) message += ` Incomplete KPI data in: ${[...partial].map(label).join(', ')}.`;
      visible.push(message);
      return visible;
    }
    let message = `${environmentLabel(environment)} has incomplete coverage in ${incomplete.length} of ${totals.length} scoring groups (operator and selected aggregation levels).`;
    if (missing.size) message += ` Missing weighted environments in one or more groups: ${[...missing].map(environmentLabel).join(', ')}.`;
    if (partial.size) message += ` Environments with missing valid KPI measurements: ${[...partial].map(environmentLabel).join(', ')}.`;
    if (!missing.size && !partial.size) message += ' One or more required KPI measurements are missing or have no valid samples.';
    const available = incomplete.map(row => Number(row.available_points)).filter(Number.isFinite);
    const maximum = incomplete.map(row => Number(row.max_points)).filter(Number.isFinite);
    const range = values => {
      const low = Math.min(...values), high = Math.max(...values);
      return low === high ? formatChartNumber(low) : `${formatChartNumber(low)}–${formatChartNumber(high)}`;
    };
    if (available.length && maximum.length) message += ` Available maximum points: ${range(available)} of ${range(maximum)}; these are scoring weights, not earned scores.`;
    const cities = job?.context_filters?.City || [];
    if (missing.size && Array.isArray(cities) && cities.length) {
      message += ` The saved City filter is ${cities.join(', ')}. Only matching City names are included; road routes with different City names are excluded.`;
    }
    if (environment === 'Combined' && (payload.aggregation_levels || job?.aggregation_levels || []).includes('City')) {
      message += ' City is an aggregation level: cities and road routes are scored separately, and environment coverage is checked within each group.';
    }
    message += ' Available points keep their original weights; missing contributions are not scaled up to a complete benchmark.';
    visible.push(message);
    return visible;
  }

  function syncResultEnvironment(tables, {payload = {}, applyCoverageDefault = false} = {}) {
    const environments = availableScoreEnvironments(tables);
    if (!environments.length) {
      currentEffectiveEnvironment = null;
      environmentSelect.disabled = true;
      environmentControl.hidden = false;
      return {environments, effective: null, unavailable: false};
    }
    if (!environments.includes(selectedEnvironment)) {
      selectedEnvironment = 'all';
    }
    if (applyCoverageDefault && !scoringEnvironmentIsComplete(payload, tables, 'Combined')
        && (selectedEnvironment === 'all' || !scoringEnvironmentIsComplete(payload, tables, selectedEnvironment))) {
      const completeEnvironment = environments.find(environment => environment !== 'all'
        && scoringEnvironmentIsComplete(payload, tables, environment));
      if (completeEnvironment) selectedEnvironment = completeEnvironment;
    }
    const currentOptions = [...environmentSelect.options].map(option => option.value);
    if (JSON.stringify(currentOptions) !== JSON.stringify(environments)) {
      environmentSelect.replaceChildren();
      for (const environment of environments) {
        const option = document.createElement('option');
        option.value = environment;
        option.textContent = environment === 'all' ? 'All Environments'
          : String(payload.configuration?.scope?.environments?.[environment]?.display_name || environment);
        environmentSelect.append(option);
      }
    }
    environmentSelect.value = selectedEnvironment;
    environmentSelect.disabled = false;
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

  function renderResult(savedPayload, job, panesToRender = [activeResultTab]) {
    currentResults = savedPayload;
    currentResultsJobId = jobIdOf(job || savedPayload.job || {}) || null;
    syncResultScoring(savedPayload);
    const payload = activeScoringPayload(savedPayload);
    const shouldRenderPane = name => panesToRender.includes(name);
    const scoringRows = payload.scoring ?? payload.scoring_rows ?? [];
    const gapRows = payload.gap ?? payload.gap_rows ?? [];
    const scoringPane = root.querySelector('[data-result-pane="scoring"]');
    const chartPane = root.querySelector('[data-result-pane="charts"]');
    const gapPane = root.querySelector('[data-result-pane="gap"]');
    const views = payload.views && typeof payload.views === 'object' ? payload.views : {};
    const allScoreTables = normalizeRows(views.score_tables ?? payload.score_tables ?? payload.scoring_views?.score_tables ?? []);
    const allGapTables = normalizeRows(views.gap_tables ?? payload.gap_tables ?? payload.scoring_views?.gap_tables ?? []);
    const allGapSummaryTables = normalizeRows(views.gap_summary_tables ?? payload.gap_summary_tables ?? payload.scoring_views?.gap_summary_tables ?? []);
    const allHierarchyScoreTables = normalizeRows(views.hierarchy_score_tables ?? []);
    const allHierarchyGapTables = normalizeRows(views.hierarchy_gap_tables ?? []);
    const applyCoverageDefault = environmentDefaultJobId !== currentResultsJobId;
    const environmentSelection = syncResultEnvironment([...allScoreTables, ...allHierarchyScoreTables], {
      payload, applyCoverageDefault,
    });
    environmentDefaultJobId = currentResultsJobId;
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
        detailHeading.textContent = 'Scoring Tables — Breakdown';
        const detailTable = document.createElement('div');
        detailTable.className = 'scoring-table-section';
        renderTable(detailTable, detailRows, 'No KPI detail rows are available.', {hideGapColumns: true});
        scoringPane.append(detailHeading, detailTable);
      } else {
        scoringPane.replaceChildren();
        renderTable(scoringPane, detailRows, 'This job has no scoring table rows.', {hideGapColumns: true});
      }
      renderCampaignComparisons(scoringPane, payload, effectiveEnvironment);
    }
    if (shouldRenderPane('charts')) {
      chartPane.classList.remove('scoring-chart-grid');
      if (hierarchyScoreTable) renderHierarchyCharts(chartPane, hierarchyScoreTable);
      else renderCharts(chartPane, chartRowsForEnvironment(payload.charts ?? [], allScoreTables, effectiveEnvironment), scoreTables);
      renderCategoryAllocation(chartPane, scoreTables, hierarchyScoreTable, allScoreTables);
      renderBestNetworkChart(chartPane, scoreTables, hierarchyScoreTable, allScoreTables);
      renderInsightCharts(chartPane, payload, effectiveEnvironment);
    }
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
      renderKpiGapProfiles(gapPane, payload, effectiveEnvironment);
      renderPointsLossMaps(gapPane, payload, effectiveEnvironment, jobIdOf(job || payload.job || {}));
    }
    const warnings = payload.warnings ?? job?.warnings ?? [];
    renderWarnings(scoringCoverageWarnings({...payload, warnings}, job, effectiveEnvironment));
    // Scaling concerns the Combined scores, not the score of a single environment.
    renderNotices(!effectiveEnvironment || ['all', 'Combined'].includes(effectiveEnvironment) ? payload.notices ?? job?.notices ?? [] : []);
    setExportLinks(jobIdOf(job || payload.job || {}), true);
  }

  function renderNoResult(text) {
    environmentControl.hidden = false;
    syncResultScoring(null);
    environmentSelect.disabled = true;
    for (const pane of resultPanes) {
      disconnectScoringValueObservers(pane);
      pane.replaceChildren();
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = text;
      pane.append(empty);
    }
    root.querySelector('[data-warning-box]').hidden = true;
    renderNotices([]);
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
      for (const job of jobs) {
        const id = jobIdOf(job);
        const cached = resultCache.get(id);
        if (cached && (isActive(job) || cached.job?.updated_at !== job.updated_at)) resultCache.delete(id);
      }
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
      calculationMatchKey = '';
      updateSelection();
      const anyActive = jobs.some(isActive);
      if (anyActive && !timer) timer = window.setInterval(refreshJobs, 3500);
      if (!anyActive && timer) { window.clearInterval(timer); timer = null; }
    } catch (error) {
      jobList.innerHTML = '';
      const empty = document.createElement('div');
      empty.className = 'scoring-empty';
      empty.textContent = error.message || 'Scoring jobs could not be loaded.';
      jobList.append(empty);
      syncJobLists();
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
      calculationMatchKey = '';
      updateSelection();
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
    const payload = {...calculationPayload(), force};
    // A new scoring always opens on Scoring Charts.
    showResultTab('charts');
    syncResultTableControls();
    persistScoringViewState();
    submittingCalculation = true;
    ++calculationMatchRevision;
    window.clearTimeout(calculationMatchTimer);
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
      if (force) resultCache.delete(id);
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
      submittingCalculation = false;
      calculationMatchKey = '';
      updateSelection();
    }
  }

  root.querySelectorAll('[data-scoring-select-datasets]').forEach(button => {
    button.addEventListener('click', () => {
      const choice = button.dataset.scoringSelectDatasets;
      if (choice === 'all') {
        for (const option of datasetOptions) {
          const input = option.querySelector('[data-dataset-id]');
          if (input) input.checked = !option.hidden;
        }
      } else {
        selectLatestDatasetForEachKind(choice === 'latest-two' ? 2 : 1);
      }
      updateSelection();
      scheduleSelectionSave();
    });
  });

  datasetInputs.forEach(input => input.addEventListener('change', () => {
    updateSelection();
    scheduleSelectionSave();
  }));
  nrFilter.addEventListener('change', () => {
    applyNrFilter(true);
    scheduleSelectionSave();
  });
  root.addEventListener('change', event => {
    if ([environmentSelect, scoringKindSelect, showKpiValuesToggle, showGapValuesToggle, gapLayoutSelect].includes(event.target)) {
      if (event.target === environmentSelect) selectedEnvironment = environmentSelect.value;
      if (event.target === scoringKindSelect) selectedScoring = scoringKindSelect.value === 'most_reliable' ? 'most_reliable' : 'best_network';
      persistScoringViewState();
    }
    if (event.target === scoringProfileSelect) {
      calculationMatchKey = '';
      const profile = scoringProfileById.get(scoringProfileSelect.value);
      if (profile && applyProfileHierarchy(profile.aggregation_hierarchy)) {
        setMessage(`This calculation will use ${profile.name}.`, 'success');
        scheduleSelectionSave();
      }
      return;
    }
    if (event.target === baselineInput || event.target.matches('[data-aggregation-level], [data-scoring-context-filter]')) {
      updateSelection();
      scheduleSelectionSave();
      return;
    }
    if (event.target === environmentSelect && currentResults) {
      selectedEnvironment = environmentSelect.value;
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target.matches?.('[data-insight-select]') && currentResults) {
      insightSelections.set(event.target.dataset.insightSelect, event.target.value);
      if (event.target.dataset.insightSelect === 'gap-profile') {
        // Keep the GAP comparison on the operator of the chosen profile.
        const profile = insightItems(activeScoringPayload(currentResults), 'kpi_gap_profiles', currentEffectiveEnvironment)
          .filter(item => item.operator !== item.reference)[Number(event.target.value)];
        const comparison = root.querySelector('[data-result-pane="gap"] [data-hierarchy-gap-operator], [data-result-pane="gap"] [data-gap-summary-operator]');
        const key = comparison?.dataset.hierarchyGapStateKey || comparison?.dataset.gapSummaryStateKey;
        if (profile && key && [...comparison.options].some(option => option.value === `operator:${profile.operator}`)) {
          gapComparisonSelections.set(key, `operator:${profile.operator}`);
          persistScoringViewState();
        }
      }
      renderResult(currentResults, selectedJob);
      return;
    }
    if (event.target === scoringKindSelect && currentResults) {
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
      gapComparisonSelections.set(gapSummaryOperator.dataset.gapSummaryStateKey, gapSummaryOperator.value);
      persistScoringViewState();
      renderResult(currentResults, selectedJob);
      return;
    }
    const hierarchyGapOperator = event.target.closest('[data-hierarchy-gap-operator]');
    if (hierarchyGapOperator && currentResults) {
      gapComparisonSelections.set(hierarchyGapOperator.dataset.hierarchyGapStateKey, hierarchyGapOperator.value);
      persistScoringViewState();
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
    const activeResults = activeScoringPayload(currentResults);
    const views = activeResults.views && typeof activeResults.views === 'object' ? activeResults.views : {};
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
  baselineInput.addEventListener('input', updateSelection);
  calculateButton.addEventListener('click', () => createJob(false));
  recalculateButton.addEventListener('click', () => createJob(true));
  document.addEventListener('click', event => {
    if (!jobSelector.contains(event.target)) jobSelector.open = false;
  });
  jobSelector.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    jobSelector.open = false;
    jobSelector.querySelector('summary').focus();
  });
  for (const list of jobLists) list.addEventListener('click', async event => {
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
    restoreCalculationSelectionFromJob(job);
    const fromDropdown = jobSelector.contains(button);
    jobSelector.open = false;
    if (fromDropdown) jobSelector.querySelector('summary').focus();
    persistScoringViewState();
    await loadJob(job, true);
    if (!fromDropdown && selectedJobId === jobIdOf(job)) {
      root.querySelector('.scoring-results-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
  });
  root.addEventListener('click', event => {
    const cdrButton = event.target.closest('[data-job-cdrs]');
    if (cdrButton) {
      event.preventDefault();
      const job = jobs.find(record => jobIdOf(record) === cdrButton.dataset.jobCdrs);
      if (!job) return;
      const copy = document.getElementById('info-copy');
      const previousWhiteSpace = copy?.style.whiteSpace || '';
      if (copy) copy.style.whiteSpace = 'pre-line';
      showInfoDialog(jobCdrNames(job).join('\n') || jobCdrSummary(job), {
        title: `Scoring job ${jobIdOf(job)} — CDRs`,
        onClose: () => {
          if (copy) copy.style.whiteSpace = previousWhiteSpace;
          cdrButton.focus();
        },
      });
      return;
    }
    const documentButton = event.target.closest('[data-scoring-document-export]');
    if (documentButton) {
      // Both buttons export the selected job, like the PowerPoint link of its results.
      const pptLink = root.querySelector('[data-export-ppt]');
      if (!pptLink || pptLink.getAttribute('aria-disabled') === 'true') {
        const message = 'Select a completed scoring job to export it.';
        if (typeof showInfoDialog === 'function') showInfoDialog(message, {tone: 'warning', title: 'No scoring job selected'});
        else window.alert(message);
        return;
      }
      if (window.ScoringReportEditor) {
        void openScoringReport(documentButton.dataset.scoringDocumentExport === 'word' ? 'word' : 'ppt');
        return;
      }
      if (documentButton.dataset.scoringDocumentExport === 'word') {
        const url = new URL(pptLink.href, window.location.href);
        url.pathname = url.pathname.replace(/\/export\/ppt$/, '/export/word');
        void downloadScoringDocument(url.href, 'Word');
      } else {
        void generateScoringPpt(pptLink);
      }
      return;
    }
    const exportLink = event.target.closest('.scoring-export-actions a');
    if (exportLink?.getAttribute('aria-disabled') === 'true') {
      event.preventDefault();
      return;
    }
    if (exportLink?.matches('[data-export-ppt]')) {
      event.preventDefault();
      if (window.ScoringReportEditor) void openScoringReport('ppt');
      else void generateScoringPpt(exportLink);
      return;
    }
    const tab = event.target.closest('[data-result-tab]');
    if (!tab || !root.contains(tab)) return;
    const name = tab.dataset.resultTab;
    if (activeResultTab === name) return;
    activeResultTab = name;
    syncResultTableControls();
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
  syncResultTableControls();
  applyNrFilter(false);
  loadCalculationSelection();
  refreshJobs();
})();
