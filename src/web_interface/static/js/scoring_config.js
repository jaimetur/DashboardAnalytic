globalThis.ScoringConfigMath = globalThis.ScoringConfigMath || Object.freeze({
  normalizeShares(values) {
    const weights = values.map((value) => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0);
    const total = weights.reduce((sum, value) => sum + value, 0);
    return total > 0 ? weights.map((value) => value / total) : [];
  },
  allocatePoints(total, shares) {
    return shares.map((share) => Number(total) * Number(share));
  },
});

if (typeof module !== 'undefined' && module.exports) module.exports = globalThis.ScoringConfigMath;

(() => {
  if (typeof document === 'undefined') return;
  const scoringConfigMath = globalThis.ScoringConfigMath;
  const root = document.querySelector('[data-scoring-config]');
  if (!root) return;

  const endpoint = '/api/workspace-config/scoring-configuration';
  const profilesEndpoint = '/api/workspace-config/scoring-profiles';
  const environmentSelect = root.querySelector('[data-scoring-environment]');
  const profileSelect = root.querySelector('[data-scoring-profile-select]');
  const profileActions = Array.from(root.querySelectorAll('[data-scoring-profile-action]'));
  const weightModeSelect = root.querySelector('[data-scoring-weight-mode]');
  const addKpiButton = root.querySelector('[data-scoring-add-kpi]');
  const environmentTotalPointsInput = root.querySelector('[data-environment-total-points]');
  const environmentTotalWeightInput = root.querySelector('[data-environment-total-weight]');
  const environmentTotalSummary = root.querySelector('[data-environment-total-summary]');
  const environmentTotalLabel = root.querySelector('[data-environment-total-label]');
  const distributePointsButton = root.querySelector('[data-scoring-distribute-points]');
  const createEnvironmentButton = root.querySelector('[data-scoring-environment-create]');
  const renameEnvironmentButton = root.querySelector('[data-scoring-environment-rename]');
  const deleteEnvironmentButton = root.querySelector('[data-scoring-environment-delete]');
  const environmentG1Input = root.querySelector('[data-environment-g1]');
  const environmentG2Input = root.querySelector('[data-environment-g2]');
  const profileDialog = root.querySelector('[data-scoring-profile-dialog]');
  const profileDialogEyebrow = root.querySelector('[data-profile-dialog-eyebrow]');
  const profileDialogTitle = root.querySelector('[data-profile-dialog-title]');
  const profileDialogCopy = root.querySelector('[data-profile-dialog-copy]');
  const profileDialogNameField = root.querySelector('[data-profile-dialog-name-field]');
  const profileDialogNameLabel = root.querySelector('[data-profile-dialog-name-label]');
  const profileDialogName = root.querySelector('[data-profile-dialog-name]');
  const profileDialogDistribution = root.querySelector('[data-profile-dialog-distribution]');
  const profileDialogEnvironmentFields = root.querySelector('[data-profile-dialog-environment-fields]');
  const profileDialogG1 = root.querySelector('[data-profile-dialog-g1]');
  const profileDialogG2 = root.querySelector('[data-profile-dialog-g2]');
  const profileDialogReference = root.querySelector('[data-profile-dialog-reference]');
  const profileDialogTotal = root.querySelector('[data-profile-dialog-total]');
  const profileDialogTotalLabel = root.querySelector('[data-profile-dialog-total-label]');
  const profileDialogError = root.querySelector('[data-profile-dialog-error]');
  const profileDialogConfirm = root.querySelector('[data-profile-dialog-confirm]');
  const profileDialogCancel = root.querySelector('[data-profile-dialog-cancel]');
  // Keep the fixed overlay outside panels whose backdrop filters create a containing block.
  if (profileDialog) document.body.append(profileDialog);
  const kpiForm = root.querySelector('[data-scoring-kpi-form]');
  const kpiRows = root.querySelector('[data-scoring-kpi-rows]');
  const kpiStatus = root.querySelector('[data-scoring-kpi-status]');
  const kpiSave = root.querySelector('[data-scoring-kpi-save]');
  const priorityForm = root.querySelector('[data-scoring-priority-form]');
  const priorityRows = root.querySelector('[data-scoring-priority-rows]');
  const priorityStatus = root.querySelector('[data-scoring-priority-status]');
  const prioritySave = root.querySelector('[data-scoring-priority-save]');
  const hierarchyForm = root.querySelector('[data-scoring-hierarchy-form]');
  const hierarchyRows = root.querySelector('[data-scoring-hierarchy-rows]');
  const hierarchyStatus = root.querySelector('[data-scoring-hierarchy-status]');
  const hierarchySave = root.querySelector('[data-scoring-hierarchy-save]');
  if (!environmentSelect || !kpiForm || !kpiRows || !priorityForm || !priorityRows) return;

  const anchors = [
    ['low_score', 'Low'],
    ['medium_score', 'Medium'],
    ['high_score', 'High'],
    ['ultra_score', 'Ultra'],
  ];
  const sourceKinds = [['data', 'Data'], ['voice', 'Voice'], ['speech', 'Speech']];
  const directions = [['higher_is_better', 'Higher is better'], ['lower_is_better', 'Lower is better']];
  const totalPacketLossFormula = '100 * SUM(totalpacketlost) / SUM(Packets_Sent)';
  const totalPacketLossExpression = 'IFNULL(Packets_Lost,0) + IFNULL(Packets_Discarded,0) + IFNULL(INT(Packets_Corrupted),0) + IFNULL(Packets_Not_Sent,0)';
  const defaultHierarchy = ['Operator', 'Vendor', 'Region', 'City', 'Campaign'];
  const hierarchyDimensions = new Set(defaultHierarchy);
  let profileCollection = null;
  let configuration = null;
  let activeProfileId = '';
  let hierarchyOrder = [...defaultHierarchy];
  let kpiDirty = false;
  let priorityDirty = false;
  let hierarchyDirty = false;
  let lastEnvironment = environmentSelect.value;
  let weightMode = weightModeSelect?.value || 'points';
  let nextKpiNumber = 1;
  let saveQueue = Promise.resolve();
  let profileDialogResolver = null;
  let profileDialogOptions = null;

  const clone = (value) => JSON.parse(JSON.stringify(value));

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

  const normalizeProfileCollection = (payload) => {
    if (Array.isArray(payload?.profiles)) {
      const profiles = payload.profiles
        .filter((profile) => profile && typeof profile.id === 'string' && profile.configuration)
        .map((profile) => ({id: profile.id, name: String(profile.name || 'Scoring methodology'), configuration: profile.configuration}));
      const requestedActiveId = String(payload.active_profile_id || '');
      const activeId = profiles.some((profile) => profile.id === requestedActiveId) ? requestedActiveId : profiles[0]?.id || '';
      return {active_profile_id: activeId, profiles};
    }
    if (Array.isArray(payload?.metrics)) {
      return {
        active_profile_id: 'default-methodology',
        profiles: [{id: 'default-methodology', name: 'Default methodology', configuration: payload}],
      };
    }
    throw new Error('The scoring methodology response is invalid.');
  };

  const environmentEntries = () => Object.entries(configuration?.scope?.environments || {});
  const environmentKeys = () => environmentEntries().map(([key]) => key);
  const environmentLabel = (key) => String(configuration?.scope?.environments?.[key]?.display_name
    || configuration?.scope?.environments?.[key]?.sheet || key)
    .replace(/([a-z])([A-Z])/g, '$1 $2');

  const normalizeNextKpiNumber = (config) => {
    const current = Number.isInteger(Number(config?.next_kpi_number)) ? Number(config.next_kpi_number) : 1;
    const highestExisting = Math.max(0, ...(config?.metrics || []).map((metric) => {
      const match = String(metric.code || '').match(/^K(\d+)$/i);
      return match ? Number(match[1]) : 0;
    }));
    return Math.max(1, current, highestExisting + 1);
  };

  const renderEnvironmentOptions = () => {
    const entries = environmentEntries();
    const previous = environmentSelect.value;
    environmentSelect.replaceChildren();
    entries.forEach(([key]) => {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = environmentLabel(key);
      environmentSelect.append(option);
    });
    const selected = entries.some(([key]) => key === previous) ? previous : entries[0]?.[0] || '';
    environmentSelect.value = selected;
    environmentSelect.disabled = !selected;
    lastEnvironment = selected;
    syncEnvironmentSourceFields();
    if (createEnvironmentButton) createEnvironmentButton.disabled = !configuration || entries.length >= 32;
    if (renameEnvironmentButton) renameEnvironmentButton.disabled = !configuration || !selected;
    if (deleteEnvironmentButton) deleteEnvironmentButton.disabled = !configuration || entries.length <= 1;
  };

  const syncEnvironmentSourceFields = () => {
    const environment = configuration?.scope?.environments?.[environmentSelect.value] || {};
    if (environmentG1Input && document.activeElement !== environmentG1Input) environmentG1Input.value = String(environment.g_level_1 || '');
    if (environmentG2Input && document.activeElement !== environmentG2Input) environmentG2Input.value = String(environment.g_level_2 || '');
    if (environmentG1Input) environmentG1Input.disabled = !environmentSelect.value;
    if (environmentG2Input) environmentG2Input.disabled = !environmentSelect.value;
  };

  const applyEnvironmentMapping = (scope) => {
    const entries = Object.entries(scope?.environments || {});
    const mapping = {};
    const selectors = [];
    entries.forEach(([key, environment]) => {
      const g1 = String(environment.g_level_1 || '').trim();
      const g2 = String(environment.g_level_2 || '').trim();
      if (!g1) throw new Error(`Source G_Level_1 is required for ${key}.`);
      if (g1.length > 160 || g2.length > 160) throw new Error(`Source selectors for ${key} must be 160 characters or fewer.`);
      const overlaps = selectors.some((selector) => selector.g1.toLocaleLowerCase() === g1.toLocaleLowerCase()
        && (!selector.g2 || !g2 || selector.g2.toLocaleLowerCase() === g2.toLocaleLowerCase()));
      if (overlaps) throw new Error(`The source selector for ${key} overlaps another environment. Use a unique G_Level_1 or G_Level_2 combination.`);
      selectors.push({g1, g2});
      environment.g_level_1 = g1;
      if (g2) environment.g_level_2 = g2;
      else delete environment.g_level_2;
      mapping[g2 ? `${g1} + ${g2}` : g1] = key;
    });
    scope.environment_mapping = mapping;
  };

  const currentProfile = (collection = profileCollection) => collection?.profiles?.find((profile) => profile.id === collection.active_profile_id) || null;

  const setProfileCollection = (payload) => {
    profileCollection = normalizeProfileCollection(payload);
    activeProfileId = profileCollection.active_profile_id;
    configuration = currentProfile()?.configuration || null;
    nextKpiNumber = normalizeNextKpiNumber(configuration);
    renderEnvironmentOptions();
    renderProfileControls();
  };

  const loadProfiles = () => requestJson(profilesEndpoint);

  const enqueueProfileUpdate = (update) => {
    const work = saveQueue.then(async () => {
      const latest = normalizeProfileCollection(await loadProfiles());
      const next = update(clone(latest));
      const saved = await requestJson(profilesEndpoint, {method: 'PUT', body: JSON.stringify(next)});
      setProfileCollection(saved);
      return profileCollection;
    });
    saveQueue = work.catch(() => {});
    return work;
  };

  const saveConfiguration = (update, profileId = activeProfileId) => enqueueProfileUpdate((latest) => {
    const profile = latest.profiles.find((item) => item.id === profileId);
    if (!profile) throw new Error('The selected scoring methodology is no longer available.');
    profile.configuration = update(profile.configuration);
    return latest;
  });

  const appendCell = (row, className = '') => {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    row.append(cell);
    return cell;
  };

  const appendInput = (cell, type, value, label, attributes = {}) => {
    const input = document.createElement('input');
    input.type = type;
    input.value = value === null || value === undefined ? '' : String(value);
    input.setAttribute('aria-label', label);
    Object.entries(attributes).forEach(([key, attributeValue]) => input.setAttribute(key, String(attributeValue)));
    cell.append(input);
    return input;
  };

  const appendTextArea = (container, value, label, attributes = {}) => {
    const textarea = document.createElement('textarea');
    textarea.value = value === null || value === undefined ? '' : String(value);
    textarea.setAttribute('aria-label', label);
    Object.entries(attributes).forEach(([key, attributeValue]) => textarea.setAttribute(key, String(attributeValue)));
    container.append(textarea);
    return textarea;
  };

  const appendSelect = (cell, value, label, options, attributes = {}) => {
    const select = document.createElement('select');
    select.setAttribute('aria-label', label);
    Object.entries(attributes).forEach(([key, attributeValue]) => select.setAttribute(key, String(attributeValue)));
    options.forEach(([optionValue, optionLabel]) => {
      const option = document.createElement('option');
      option.value = optionValue;
      option.textContent = optionLabel;
      option.selected = String(optionValue) === String(value);
      select.append(option);
    });
    cell.append(select);
    return select;
  };

  const appendNumericInput = (cell, value, label, attributes = {}) => appendInput(
    cell, 'number', Number.isFinite(Number(value)) ? value : '', label,
    {step: 'any', ...attributes},
  );

  const rowMetrics = () => Array.from(kpiRows.querySelectorAll('tr[data-kpi-code]'));

  const metricForRow = (row) => row?._newMetricTemplate
    ? row._newMetricTemplate
    : (configuration?.metrics || []).find((metric) => metric.code === row?.dataset.originalCode) || null;

  const contextDraftsForRow = (row) => row._contextDrafts || (row._contextDrafts = {});

  const captureSelectedContext = (row, targetEnvironment = environmentSelect.value) => {
    const environment = targetEnvironment;
    const existing = row._contextDrafts?.[environment] || {};
    const thresholds = {};
    ['low', 'medium', 'high'].forEach((key) => {
      thresholds[key] = row.querySelector(`[data-threshold="${key}"]`)?.value ?? '';
    });
    const mapping = {};
    anchors.forEach(([key]) => {
      mapping[key] = row.querySelector(`[data-score-anchor="${key}"]`)?.value ?? '';
    });
    const points = row.querySelector('[data-max-points]')?.value ?? '';
    const ultraMode = row.querySelector('[data-ultra-mode]')?.value || 'none';
    const ultraValue = row.querySelector('[data-ultra-value]')?.value ?? '';
    const numericPoints = Number(points);
    const cached = {
      ...existing,
      max_points: points,
      thresholds,
      ultra_mode: ultraMode,
      ultra_value: ultraValue,
      score_mapping: mapping,
    };
    if (Number.isFinite(numericPoints)) row._contextPointDrafts = {...row._contextPointDrafts, [environment]: numericPoints};
    contextDraftsForRow(row)[environment] = cached;
  };

  const hydrateSelectedContext = (row, environment) => {
    const draft = row._contextDrafts?.[environment];
    const saved = metricForRow(row)?.contexts?.[environment] || {};
    const points = draft?.max_points ?? saved.max_points;
    const pointsInput = row.querySelector('[data-max-points]');
    if (pointsInput) pointsInput.value = points === null || points === undefined ? '0' : String(points);
    ['low', 'medium', 'high'].forEach((key) => {
      const input = row.querySelector(`[data-threshold="${key}"]`);
      const value = draft?.thresholds?.[key] ?? saved.thresholds?.[key];
      if (input) input.value = value === null || value === undefined ? '' : String(value);
    });
    const savedUltra = saved.thresholds?.ultra;
    const ultraMode = draft?.ultra_mode || (savedUltra === null || savedUltra === undefined
      ? 'none' : typeof savedUltra === 'object' ? String(savedUltra.rule || 'none') : 'fixed');
    const ultraModeInput = row.querySelector('[data-ultra-mode]');
    const ultraValueInput = row.querySelector('[data-ultra-value]');
    if (ultraModeInput) ultraModeInput.value = ultraMode;
    if (ultraValueInput) {
      const value = draft?.ultra_value ?? (typeof savedUltra === 'number' ? savedUltra : '');
      ultraValueInput.value = value === null || value === undefined ? '' : String(value);
    }
    anchors.forEach(([key]) => {
      const input = row.querySelector(`[data-score-anchor="${key}"]`);
      const raw = draft?.score_mapping?.[key] ?? Number(saved.score_mapping?.[key]) * 100;
      if (input) input.value = raw === null || raw === undefined || Number.isNaN(Number(raw)) ? '' : String(raw);
    });
    const share = draft?.weight_share ?? row._weightShareDrafts?.[environment] ?? saved.weight_share;
    if (Number.isFinite(Number(share))) setRowEnvironmentShare(row, environment, Number(share));
    syncUltraInput(row);
  };

  const pointsForRow = (row, environment) => {
    if (environment === environmentSelect.value) {
      const value = Number(row.querySelector('[data-max-points]')?.value);
      return Number.isFinite(value) ? value : 0;
    }
    const draft = Number(row._contextPointDrafts?.[environment]);
    if (Number.isFinite(draft)) return draft;
    const value = Number(metricForRow(row)?.contexts?.[environment]?.max_points);
    return Number.isFinite(value) ? value : 0;
  };

  const setRowEnvironmentPoints = (row, environment, points) => {
    row._contextPointDrafts = row._contextPointDrafts || {};
    row._contextPointDrafts[environment] = points;
    contextDraftsForRow(row)[environment] = {
      ...(row._contextDrafts?.[environment] || {}),
      max_points: String(points),
    };
    if (environment === environmentSelect.value) {
      const input = row.querySelector('[data-max-points]');
      if (input) input.value = String(points);
    }
  };

  const setRowEnvironmentShare = (row, environment, share) => {
    row._weightShareDrafts = row._weightShareDrafts || {};
    row._weightShareDrafts[environment] = share;
    contextDraftsForRow(row)[environment] = {
      ...(row._contextDrafts?.[environment] || {}),
      weight_share: share,
    };
  };

  const environmentTotalFor = (environment, rows = rowMetrics()) => rows.reduce(
    (sum, row) => sum + pointsForRow(row, environment), 0,
  );

  const globalPointsTotal = (rows = rowMetrics()) => environmentKeys().reduce(
    (sum, environment) => sum + environmentTotalFor(environment, rows), 0,
  );

  const normalizeShares = (values) => {
    return scoringConfigMath.normalizeShares(values);
  };

  const environmentWeightShares = (environment, rows = rowMetrics()) => {
    const totalPoints = environmentTotalFor(environment, rows);
    if (totalPoints > 0) return {shares: rows.map((row) => pointsForRow(row, environment) / totalPoints), source: 'points'};

    const stored = rows.map((row) => {
      const draft = Number(row._weightShareDrafts?.[environment]);
      if (Number.isFinite(draft) && draft >= 0) return draft;
      const value = Number(metricForRow(row)?.contexts?.[environment]?.weight_share);
      return Number.isFinite(value) && value >= 0 ? value : 0;
    });
    const storedShares = normalizeShares(stored);
    if (storedShares.length) return {shares: storedShares, source: 'saved'};

    const baseEnvironment = environmentKeys().includes('DriveCity') ? 'DriveCity' : environmentKeys()[0];
    const baseWeights = rows.map((row) => Number(metricForRow(row)?.contexts?.[baseEnvironment]?.max_points) || 0);
    const baseShares = normalizeShares(baseWeights);
    if (baseShares.length) return {shares: baseShares, source: 'city'};

    return {shares: rows.length ? rows.map(() => 1 / rows.length) : [], source: 'equal'};
  };

  const deriveDenominator = (formula) => {
    const normalized = String(formula || '').trim();
    const ratio = normalized.match(/^(?:100\s*\*\s*)?(?:SUM|COUNT)\((.+)\)\s*\/\s*(SUM|COUNT)\(([A-Za-z_]\w*)\)$/i);
    if (ratio) return ratio[2].toUpperCase() === 'SUM' ? `Sum of ${ratio[3]}` : `Non-null ${ratio[3]} rows`;
    const aggregate = normalized.match(/^(AVG|MEDIAN|PCT90|SUM|COUNT)\((.+)\)$/i);
    if (!aggregate) return 'Valid observations for this KPI';
    const operation = aggregate[1].toUpperCase();
    const expression = aggregate[2].trim();
    const field = expression.split('|')[0].trim();
    if (operation === 'COUNT') return expression.includes('|') ? `Rows matching ${expression}` : `Non-null ${field} rows`;
    if (operation === 'SUM') return expression.includes('|') ? `Sum of ${field} values for matching rows` : `Sum of ${field} values`;
    return expression.includes('|') ? `Valid observations matching ${expression}` : `Valid ${field} observations`;
  };

  const updateEnvironmentTotalSummary = () => {
    const rows = rowMetrics();
    const totalPoints = environmentTotalFor(environmentSelect.value, rows);
    const allPoints = globalPointsTotal(rows);
    const globalShare = allPoints > 0 ? totalPoints * 100 / allPoints : 0;
    if (environmentTotalSummary) {
      environmentTotalSummary.textContent = `${totalPoints.toFixed(2)} points · ${globalShare.toFixed(2)}% of global points`;
    }
    if (environmentTotalPointsInput && document.activeElement !== environmentTotalPointsInput) {
      environmentTotalPointsInput.value = totalPoints.toFixed(2);
      environmentTotalPointsInput.removeAttribute('aria-invalid');
    }
    if (environmentTotalWeightInput && document.activeElement !== environmentTotalWeightInput) {
      environmentTotalWeightInput.value = globalShare.toFixed(2);
      environmentTotalWeightInput.removeAttribute('aria-invalid');
    }
    if (environmentTotalPointsInput) environmentTotalPointsInput.setAttribute('aria-label', `Total points for ${environmentLabel(environmentSelect.value)}`);
    if (environmentTotalWeightInput) environmentTotalWeightInput.setAttribute('aria-label', `Global weight percentage for ${environmentLabel(environmentSelect.value)}`);
  };

  const updateCategoryTotals = () => {
    const rows = rowMetrics();
    const environment = environmentSelect.value;
    const environmentTotal = environmentTotalFor(environment, rows);
    const globalTotal = globalPointsTotal(rows);
    const shares = environmentWeightShares(environment, rows).shares;
    const categories = new Map();
    rows.forEach((row, index) => {
      const category = row.querySelector('[data-kpi-category]')?.value.trim() || 'Other';
      const points = pointsForRow(row, environment);
      const current = categories.get(category) || {points: 0, share: 0};
      current.points += Number.isFinite(points) ? points : 0;
      current.share += shares[index] || 0;
      categories.set(category, current);
    });
    Array.from(kpiRows.querySelectorAll('tr[data-kpi-category-heading]')).forEach((heading) => {
      const totals = categories.get(heading.dataset.kpiCategoryHeading) || {points: 0, share: 0};
      heading.querySelector('[data-category-points]').textContent = `${totals.points.toFixed(2)} points in ${environmentLabel(environmentSelect.value)}`;
      const environmentPercent = environmentTotal > 0 ? totals.points * 100 / environmentTotal : totals.share * 100;
      heading.querySelector('[data-category-weight]').textContent = `Environment weight: ${environmentPercent.toFixed(2)}%`;
      heading.querySelector('[data-category-global-weight]').textContent = `Global weight: ${globalTotal > 0 ? (totals.points * 100 / globalTotal).toFixed(2) : '0.00'}%`;
    });
  };

  const updateDerivedWeights = () => {
    const rows = rowMetrics();
    const currentEnvironment = environmentSelect.value;
    const environmentTotal = environmentTotalFor(currentEnvironment, rows);
    const globalTotal = globalPointsTotal(rows);
    const relativeShares = environmentWeightShares(currentEnvironment, rows).shares;
    rows.forEach((row, index) => {
      const points = pointsForRow(row, currentEnvironment);
      const environmentPercent = (relativeShares[index] || 0) * 100;
      const globalPercent = globalTotal > 0 ? points * 100 / globalTotal : 0;
      const pointInput = row.querySelector('[data-max-points]');
      const pointOutput = row.querySelector('[data-max-points-output]');
      const environmentOutput = row.querySelector('[data-weight-environment-percent]');
      const environmentInput = row.querySelector('[data-weight-environment-input]');
      const globalOutput = row.querySelector('[data-weight-global-percent]');
      if (pointInput && document.activeElement !== pointInput) pointInput.value = String(points);
      if (pointOutput) pointOutput.textContent = points.toFixed(2);
      if (environmentOutput) environmentOutput.textContent = `${environmentPercent.toFixed(2)}%`;
      if (environmentInput && document.activeElement !== environmentInput) {
        environmentInput.value = environmentPercent.toFixed(2);
        environmentInput.removeAttribute('aria-invalid');
      }
      if (globalOutput) globalOutput.textContent = `${globalPercent.toFixed(2)}%`;
    });
    if (environmentTotalPointsInput) environmentTotalPointsInput.disabled = !configuration;
    if (environmentTotalWeightInput) environmentTotalWeightInput.disabled = !configuration;
    updateEnvironmentTotalSummary();
    updateCategoryTotals();
  };

  const syncWeightMode = () => {
    rowMetrics().forEach((row) => {
      const pointsInput = row.querySelector('[data-max-points]');
      const pointsOutput = row.querySelector('[data-max-points-output]');
      const weightInput = row.querySelector('[data-weight-environment-input]');
      const weightOutput = row.querySelector('[data-weight-environment-percent]');
      if (pointsInput) {
        pointsInput.hidden = weightMode !== 'points';
        pointsInput.disabled = weightMode !== 'points';
      }
      if (pointsOutput) pointsOutput.hidden = weightMode === 'points';
      if (weightInput) {
        weightInput.hidden = weightMode !== 'weight';
        weightInput.disabled = weightMode !== 'weight';
      }
      if (weightOutput) weightOutput.hidden = weightMode === 'weight';
    });
    if (environmentTotalPointsInput) {
      environmentTotalPointsInput.hidden = weightMode !== 'points';
      environmentTotalPointsInput.disabled = weightMode !== 'points' || !configuration;
    }
    if (environmentTotalWeightInput) {
      environmentTotalWeightInput.hidden = weightMode !== 'weight';
      environmentTotalWeightInput.disabled = weightMode !== 'weight' || !configuration;
    }
    if (environmentTotalLabel) {
      environmentTotalLabel.textContent = weightMode === 'weight'
        ? 'Environment weight (% of global points)'
        : 'Environment total (points)';
    }
  };

  const syncUltraInput = (row) => {
    const mode = row.querySelector('[data-ultra-mode]')?.value;
    const direction = row.querySelector('[data-kpi-direction]')?.value;
    const input = row.querySelector('[data-ultra-value]');
    const note = row.querySelector('[data-ultra-note]');
    const ultraSelect = row.querySelector('[data-ultra-mode]');
    Array.from(ultraSelect?.options || []).forEach((option) => {
      if (option.value === 'best_min') option.disabled = direction !== 'lower_is_better';
      if (option.value === 'best_max') option.disabled = direction !== 'higher_is_better';
    });
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

  const syncFormulaDependentControls = (row) => {
    const formula = row.querySelector('[data-kpi-formula]')?.value || '';
    const denominator = row.querySelector('[data-kpi-denominator]');
    if (denominator) denominator.textContent = deriveDenominator(formula);
    const packetLossLabel = row.querySelector('[data-kpi-total-packet-loss]')?.closest('label');
    const packetLossInput = row.querySelector('[data-kpi-total-packet-loss]');
    const usesTotalPacketLoss = formula.trim() === totalPacketLossFormula;
    if (packetLossLabel) packetLossLabel.hidden = !usesTotalPacketLoss;
    if (packetLossInput && usesTotalPacketLoss) packetLossInput.value = totalPacketLossExpression;
  };

  const makeCategoryHeading = (category) => {
    const row = document.createElement('tr');
    row.className = 'scoring-config-category-row';
    row.dataset.kpiCategoryHeading = category;
    const cell = document.createElement('th');
    cell.scope = 'colgroup';
    cell.colSpan = 18;
    const name = document.createElement('span');
    name.textContent = category;
    const totals = document.createElement('span');
    totals.className = 'scoring-config-category-total';
    const points = document.createElement('span');
    points.dataset.categoryPoints = '';
    const weight = document.createElement('span');
    weight.dataset.categoryWeight = '';
    weight.title = 'Category points as a percentage of the selected Environment total.';
    const globalWeight = document.createElement('span');
    globalWeight.dataset.categoryGlobalWeight = '';
    globalWeight.title = 'Category points in the selected Environment as a percentage of the total points across all Environments.';
    totals.append(points, weight, globalWeight);
    cell.append(name, totals);
    row.append(cell);
    return row;
  };

  const renderCategoryGroups = () => {
    const rows = rowMetrics();
    const grouped = new Map();
    rows.forEach((row) => {
      const category = row.querySelector('[data-kpi-category]')?.value.trim() || 'Other';
      if (!grouped.has(category)) grouped.set(category, []);
      grouped.get(category).push(row);
    });
    const orderedCategories = Array.from(grouped.keys());
    const fragments = [];
    orderedCategories.forEach((category) => {
      fragments.push(makeCategoryHeading(category));
      grouped.get(category).sort((left, right) => Number(left.dataset.orderIndex) - Number(right.dataset.orderIndex)).forEach((row) => fragments.push(row));
    });
    kpiRows.replaceChildren(...fragments);
    updateCategoryTotals();
    refreshKpiActionButtons();
  };

  const renderKpiRow = (metric, index, {newMetric = false} = {}) => {
    const environment = environmentSelect.value;
    const context = metric.contexts?.[environment];
    if (!context) return null;
    const row = document.createElement('tr');
    row.dataset.kpiCode = metric.code;
    row.dataset.originalCode = newMetric ? '' : metric.code;
    row.dataset.orderIndex = String(index);
    if (newMetric) row._newMetricTemplate = clone(metric);

    const codeCell = appendCell(row, 'scoring-config-code-display');
    appendInput(codeCell, 'text', metric.code, `KPI code for ${metric.kpi || metric.code}`, {
      'data-kpi-code-input': '', class: 'scoring-config-code-input', maxlength: '32', required: '',
      title: 'Changing this code also updates its saved GAP priority entry.',
    });

    const kpiCell = appendCell(row, 'scoring-config-kpi-label');
    appendInput(kpiCell, 'text', metric.kpi || metric.code, `KPI label for ${metric.code}`, {
      'data-kpi-label': '', class: 'scoring-config-identity-input', maxlength: '160', required: '',
    });

    const categoryCell = appendCell(row);
    appendInput(categoryCell, 'text', metric.category || 'Other', `Category for ${metric.kpi || metric.code}`, {
      'data-kpi-category': '', class: 'scoring-config-category-input', maxlength: '100', required: '',
    });

    const typeCell = appendCell(row);
    appendInput(typeCell, 'text', metric.kpi_type || '', `Type of KPI for ${metric.kpi || metric.code}`, {
      'data-kpi-type': '', class: 'scoring-config-type-input', maxlength: '80', required: '',
    });

    const directionCell = appendCell(row);
    const directionSelect = appendSelect(directionCell, metric.direction || 'higher_is_better', `Scoring direction for ${metric.kpi || metric.code}`, directions, {
      'data-kpi-direction': '', class: 'scoring-config-direction',
    });

    const pointsCell = appendCell(row);
    appendNumericInput(pointsCell, context.max_points, `Maximum points for ${metric.kpi || metric.code}`, {
      'data-max-points': '', min: '0', required: '',
    });
    const pointsOutput = document.createElement('span');
    pointsOutput.dataset.maxPointsOutput = '';
    pointsCell.append(pointsOutput);
    const weightCell = appendCell(row, 'scoring-config-weight');
    const weightOutput = document.createElement('span');
    weightOutput.dataset.weightEnvironmentPercent = '';
    weightCell.append(weightOutput);
    appendNumericInput(weightCell, '', `Weight percentage for ${metric.kpi || metric.code}`, {
      'data-weight-environment-input': '', min: '0', max: '100', step: '0.01', required: '',
    });
    const globalWeightCell = appendCell(row, 'scoring-config-weight');
    const globalWeightOutput = document.createElement('span');
    globalWeightOutput.dataset.weightGlobalPercent = '';
    globalWeightCell.append(globalWeightOutput);

    for (const key of ['low', 'medium', 'high']) {
      const cell = appendCell(row);
      appendNumericInput(cell, context.thresholds?.[key], `${key} KPI threshold for ${metric.kpi || metric.code}`, {
        'data-threshold': key, required: '',
      });
    }

    const ultraCell = appendCell(row, 'scoring-config-ultra');
    const ultraEditor = document.createElement('div');
    ultraEditor.className = 'scoring-config-ultra-editor';
    const ultra = context.thresholds?.ultra;
    const ultraMode = ultra === null || ultra === undefined ? 'none' : typeof ultra === 'object' ? String(ultra.rule || 'none') : 'fixed';
    appendSelect(ultraEditor, ultraMode, `Ultra threshold type for ${metric.kpi || metric.code}`, [
      ['none', 'None'], ['fixed', 'Fixed value'], ['best_min', 'Best minimum'], ['best_max', 'Best maximum'],
    ], {'data-ultra-mode': ''});
    appendNumericInput(
      ultraEditor, typeof ultra === 'number' ? ultra : '', `Fixed Ultra threshold for ${metric.kpi || metric.code}`,
      {'data-ultra-value': '', required: ''},
    );
    const ultraNote = document.createElement('small');
    ultraNote.dataset.ultraNote = '';
    ultraEditor.append(ultraNote);
    ultraCell.append(ultraEditor);

    const mapping = context.score_mapping || {};
    anchors.forEach(([key, label]) => {
      const cell = appendCell(row);
      appendNumericInput(cell, Number(mapping[key]) * 100, `${label} score interpolation anchor for ${metric.kpi || metric.code}`, {
        'data-score-anchor': key, min: '0', max: '100', required: '',
      });
    });

    const calculationCell = appendCell(row, 'scoring-config-source');
    const details = document.createElement('details');
    details.className = 'scoring-config-source';
    const summary = document.createElement('summary');
    summary.textContent = 'Edit formula and filters';
    details.append(summary);
    const sourceLabel = document.createElement('label');
    sourceLabel.textContent = 'Source kind';
    appendSelect(sourceLabel, metric.source_kind || metric.calculation?.source_kind || 'data', `Source kind for ${metric.kpi || metric.code}`, sourceKinds, {
      'data-kpi-source-kind': '', class: 'scoring-config-source-kind',
    });
    const formulaEditor = document.createElement('div');
    formulaEditor.className = 'scoring-config-formula';
    const formulaLabel = document.createElement('label');
    formulaLabel.textContent = 'Formula';
    appendTextArea(formulaLabel, metric.calculation?.formula || '', `Formula for ${metric.kpi || metric.code}`, {
      'data-kpi-formula': '', rows: '4', required: '',
    });
    const filtersLabel = document.createElement('label');
    filtersLabel.textContent = 'Filter rules (JSON object)';
    appendTextArea(filtersLabel, JSON.stringify(metric.calculation?.filters || {}, null, 2), `Filter rules for ${metric.kpi || metric.code}`, {
      'data-kpi-filters': '', rows: '5', required: '',
    });
    const denominatorLabel = document.createElement('label');
    denominatorLabel.textContent = 'Calculation basis (derived from formula)';
    const denominatorOutput = document.createElement('output');
    denominatorOutput.dataset.kpiDenominator = '';
    denominatorOutput.setAttribute('aria-label', `Calculation basis for ${metric.kpi || metric.code}`);
    denominatorOutput.title = 'Derived from the formula; it does not change the calculation.';
    denominatorOutput.textContent = deriveDenominator(metric.calculation?.formula || '');
    denominatorLabel.append(denominatorOutput);
    const denominatorNote = document.createElement('small');
    denominatorNote.className = 'scoring-config-denominator-note';
    denominatorNote.textContent = 'Informational only; the formula determines the calculation.';
    denominatorLabel.append(denominatorNote);
    const packetLossLabel = document.createElement('label');
    packetLossLabel.textContent = 'Total packet loss expression (fixed engine rule)';
    const packetLossInput = appendTextArea(packetLossLabel, metric.calculation?.totalpacketlost || totalPacketLossExpression, `Fixed total packet loss expression for ${metric.kpi || metric.code}`, {
      'data-kpi-total-packet-loss': '', rows: '3', readonly: '', title: 'This allowlisted expression is fixed by the scoring engine.',
    });
    packetLossInput.placeholder = totalPacketLossExpression;
    packetLossLabel.hidden = String(metric.calculation?.formula || '').trim() !== totalPacketLossFormula;
    formulaEditor.append(formulaLabel, filtersLabel, denominatorLabel, packetLossLabel);
    details.append(sourceLabel, formulaEditor);
    calculationCell.append(details);
    directionSelect.addEventListener('change', () => syncUltraInput(row));
    row.querySelector('[data-ultra-mode]')?.addEventListener('change', () => syncUltraInput(row));
    syncUltraInput(row);

    const actions = document.createElement('div');
    actions.className = 'scoring-config-kpi-actions';
    const addBelow = document.createElement('button');
    addBelow.type = 'button';
    addBelow.className = 'ghost-link';
    addBelow.dataset.kpiAddBelow = '';
    addBelow.setAttribute('aria-label', `Add KPI below ${metric.kpi || metric.code} in this category`);
    addBelow.title = 'Add a KPI below this row in the same category';
    addBelow.textContent = 'Add below';
    actions.append(addBelow);
    for (const [directionName, label] of [['up', 'Move up within category'], ['down', 'Move down within category']]) {
      const move = document.createElement('button');
      move.type = 'button';
      move.className = 'ghost-link';
      move.dataset.kpiMove = directionName;
      move.setAttribute('aria-label', `${label}: ${metric.kpi || metric.code}`);
      move.title = label;
      move.textContent = directionName === 'up' ? '↑' : '↓';
      actions.append(move);
    }
    const actionsCell = appendCell(row);
    actionsCell.append(actions);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'ghost-link scoring-config-delete-kpi';
    remove.dataset.kpiDelete = '';
    remove.setAttribute('aria-label', `Delete KPI ${metric.kpi || metric.code}`);
    remove.title = 'Delete KPI';
    remove.textContent = 'Delete';
    actions.append(remove);
    const formulaInput = row.querySelector('[data-kpi-formula]');
    formulaInput?.addEventListener('input', () => syncFormulaDependentControls(row));
    syncFormulaDependentControls(row);
    return row;
  };

  const refreshKpiActionButtons = () => {
    const rows = rowMetrics();
    const categories = new Map();
    rows.forEach((row) => {
      const category = row.querySelector('[data-kpi-category]')?.value.trim() || 'Other';
      if (!categories.has(category)) categories.set(category, []);
      categories.get(category).push(row);
    });
    rows.forEach((row) => {
      const category = row.querySelector('[data-kpi-category]')?.value.trim() || 'Other';
      const peers = categories.get(category) || [];
      const categoryIndex = peers.indexOf(row);
      const up = row.querySelector('[data-kpi-move="up"]');
      const down = row.querySelector('[data-kpi-move="down"]');
      const remove = row.querySelector('[data-kpi-delete]');
      if (up) up.disabled = categoryIndex <= 0;
      if (down) down.disabled = categoryIndex < 0 || categoryIndex >= peers.length - 1;
      if (remove) remove.disabled = rows.length <= 1;
    });
  };

  const renderKpiRows = () => {
    kpiRows.replaceChildren();
    const metrics = Array.isArray(configuration?.metrics) ? configuration.metrics : [];
    metrics.forEach((metric, index) => {
      const row = renderKpiRow(metric, index);
      if (row) kpiRows.append(row);
    });
    renderCategoryGroups();
    refreshKpiActionButtons();
    syncWeightMode();
    updateDerivedWeights();
    if (kpiSave) kpiSave.disabled = false;
    if (addKpiButton) addKpiButton.disabled = !configuration;
    if (distributePointsButton) distributePointsButton.disabled = !configuration || !environmentKeys().length;
  };

  const priorityMetric = (code) => (configuration?.metrics || []).find((metric) => metric.code === code);
  const priorityLabel = (code) => {
    const metric = priorityMetric(code);
    return metric ? (metric.kpi || metric.code) : code;
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
      appendCell(row).textContent = priorityMetric(code)?.category || 'Other';
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

  const normalizeHierarchy = (value) => {
    const items = Array.isArray(value) ? value.map((item) => String(item)) : [];
    return items.length === defaultHierarchy.length
      && new Set(items).size === defaultHierarchy.length
      && items.every((item) => hierarchyDimensions.has(item))
      ? items : [...defaultHierarchy];
  };

  const refreshHierarchyButtons = () => {
    const rows = Array.from(hierarchyRows?.querySelectorAll('tr[data-aggregation-level]') || []);
    rows.forEach((row, index) => {
      row.querySelector('[data-hierarchy-rank]').textContent = String(index + 1);
      row.querySelector('[data-hierarchy-move="up"]').disabled = index === 0;
      row.querySelector('[data-hierarchy-move="down"]').disabled = index === rows.length - 1;
    });
    if (hierarchySave) hierarchySave.disabled = !configuration || rows.length !== defaultHierarchy.length;
  };

  const renderHierarchyRows = () => {
    if (!hierarchyRows) return;
    hierarchyRows.replaceChildren();
    hierarchyOrder.forEach((level, index) => {
      const row = document.createElement('tr');
      row.dataset.aggregationLevel = level;
      const rank = document.createElement('span');
      rank.dataset.hierarchyRank = '';
      rank.textContent = String(index + 1);
      appendCell(row).append(rank);
      const levelCell = appendCell(row, 'scoring-config-hierarchy-level');
      levelCell.append(document.createTextNode(level));
      if (level === 'Operator') {
        const required = document.createElement('span');
        required.className = 'scoring-config-hierarchy-required';
        required.textContent = 'Required';
        levelCell.append(required);
      }
      const actions = document.createElement('div');
      actions.className = 'scoring-config-priority-actions';
      for (const [direction, label] of [['up', 'Move up'], ['down', 'Move down']]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.hierarchyMove = direction;
        button.setAttribute('aria-label', `${label}: ${level}`);
        button.title = label;
        button.textContent = direction === 'up' ? '↑' : '↓';
        actions.append(button);
      }
      appendCell(row).append(actions);
      hierarchyRows.append(row);
    });
    refreshHierarchyButtons();
  };

  const renderProfileControls = () => {
    if (profileSelect) {
      profileSelect.replaceChildren();
      (profileCollection?.profiles || []).forEach((profile) => {
        const option = document.createElement('option');
        option.value = profile.id;
        option.textContent = profile.id === profileCollection.active_profile_id ? `${profile.name} · Active` : profile.name;
        option.selected = profile.id === profileCollection.active_profile_id;
        profileSelect.append(option);
      });
      profileSelect.disabled = !profileCollection?.profiles?.length;
    }
    const hasProfile = Boolean(currentProfile());
    profileActions.forEach((button) => {
      button.disabled = !hasProfile || (button.dataset.scoringProfileAction === 'delete' && (profileCollection?.profiles?.length || 0) <= 1);
    });
    if (addKpiButton) addKpiButton.disabled = !configuration;
  };

  const render = () => {
    hierarchyOrder = normalizeHierarchy(configuration?.aggregation_hierarchy);
    renderHierarchyRows();
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

  const readText = (row, selector, label) => {
    const input = row.querySelector(selector);
    const value = input?.value.trim();
    if (!value) throw new Error(`${label} is required.`);
    if (input && !input.checkValidity()) {
      input.reportValidity();
      throw new Error(`${label} has an invalid value.`);
    }
    return value;
  };

  const parseFilters = (row, metricLabel) => {
    const input = row.querySelector('[data-kpi-filters]');
    let filters;
    try {
      filters = JSON.parse(input.value);
    } catch {
      input.focus();
      throw new Error(`Filter rules for ${metricLabel} must be valid JSON.`);
    }
    if (!filters || Array.isArray(filters) || typeof filters !== 'object') {
      input.focus();
      throw new Error(`Filter rules for ${metricLabel} must be a JSON object.`);
    }
    return filters;
  };

  const readDraftNumber = (value, label, environment) => {
    if (value === null || value === undefined || String(value).trim() === '') {
      throw new Error(`${label} is required for ${environmentLabel(environment)}.`);
    }
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${label} must be finite for ${environmentLabel(environment)}.`);
    return number;
  };

  const applyCachedContextDraft = (metric, row, environment, label, direction) => {
    const draft = row._contextDrafts?.[environment];
    if (!draft) return;
    const context = metric.contexts[environment] || (metric.contexts[environment] = {});
    const maxPoints = readDraftNumber(draft.max_points ?? context.max_points, `Maximum points for ${label}`, environment);
    if (maxPoints < 0) throw new Error(`Maximum points for ${label} cannot be negative in ${environmentLabel(environment)}.`);
    const thresholds = {};
    ['low', 'medium', 'high'].forEach((key) => {
      thresholds[key] = readDraftNumber(draft.thresholds?.[key] ?? context.thresholds?.[key], `${key} threshold for ${label}`, environment);
    });
    const monotonic = direction === 'higher_is_better'
      ? thresholds.low <= thresholds.medium && thresholds.medium <= thresholds.high
      : thresholds.low >= thresholds.medium && thresholds.medium >= thresholds.high;
    if (!monotonic) {
      throw new Error(`${label} thresholds in ${environmentLabel(environment)} must follow the selected direction: low, medium and high must move in KPI quality order.`);
    }
    const scoreMapping = {};
    anchors.forEach(([key, anchorLabel]) => {
      const anchor = readDraftNumber(draft.score_mapping?.[key] ?? Number(context.score_mapping?.[key]) * 100, `${anchorLabel} score interpolation anchor for ${label}`, environment);
      if (anchor < 0 || anchor > 100) throw new Error(`${anchorLabel} score interpolation anchor for ${label} must be between 0 and 100 in ${environmentLabel(environment)}.`);
      scoreMapping[key] = anchor / 100;
    });
    const storedUltra = context.thresholds?.ultra;
    const ultraMode = draft.ultra_mode || (storedUltra === null || storedUltra === undefined
      ? 'none' : typeof storedUltra === 'object' ? String(storedUltra.rule || 'none') : 'fixed');
    let ultra;
    if (ultraMode === 'none') ultra = null;
    else if (ultraMode === 'fixed') {
      ultra = readDraftNumber(draft.ultra_value ?? (typeof storedUltra === 'number' ? storedUltra : ''), `Ultra threshold for ${label}`, environment);
      if (direction === 'higher_is_better' && ultra < thresholds.high) {
        throw new Error(`${label} Ultra threshold in ${environmentLabel(environment)} must be at least its high threshold for the selected direction.`);
      }
      if (direction === 'lower_is_better' && ultra > thresholds.high) {
        throw new Error(`${label} Ultra threshold in ${environmentLabel(environment)} must be at most its high threshold for the selected direction.`);
      }
    } else {
      const expectedUltraMode = direction === 'higher_is_better' ? 'best_max' : 'best_min';
      if (ultraMode !== expectedUltraMode) {
        throw new Error(`${label} Ultra rule in ${environmentLabel(environment)} must match the selected direction. Choose ${expectedUltraMode === 'best_max' ? 'Best maximum' : 'Best minimum'}, Fixed value or None.`);
      }
      const previousUltra = context.thresholds?.ultra;
      ultra = {
        rule: ultraMode,
        ...(previousUltra && typeof previousUltra === 'object' && previousUltra.source_formula
          ? {source_formula: previousUltra.source_formula} : {}),
      };
    }
    context.max_points = maxPoints;
    context.thresholds = {...(context.thresholds || {}), ...thresholds, ultra};
    context.score_mapping = {...(context.score_mapping || {}), ...scoreMapping};
  };

  const selectedWeightInputsValid = () => rowMetrics().every((row) => {
    const input = row.querySelector('[data-weight-environment-input]');
    return !input?.getAttribute('aria-invalid');
  }) && !environmentTotalPointsInput?.getAttribute('aria-invalid')
    && !environmentTotalWeightInput?.getAttribute('aria-invalid');

  const readKpiRows = (latestConfiguration, environment) => {
    const rows = rowMetrics();
    rows.forEach(captureSelectedContext);
    if (!rows.length) throw new Error('A scoring methodology must contain at least one KPI.');
    if (!environmentKeys().length || globalPointsTotal(rows) <= 0) {
      throw new Error('A scoring methodology must contain at least one environment and a positive total of environment points.');
    }
    if (!selectedWeightInputsValid()) throw new Error('Correct the invalid weight percentage before saving.');
    latestConfiguration.scope = clone(configuration.scope);
    applyEnvironmentMapping(latestConfiguration.scope);
    const entries = rows.map((row) => {
      const originalCode = row.dataset.originalCode;
      const previous = (latestConfiguration.metrics || []).find((metric) => metric.code === originalCode);
      const metric = previous ? clone(previous) : clone(row._newMetricTemplate || {});
      const code = readText(row, '[data-kpi-code-input]', 'KPI code');
      if (!/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(code)) {
        throw new Error(`KPI code “${code}” must start with a letter and contain at most 32 letters, numbers, underscores or hyphens.`);
      }
      const label = readText(row, '[data-kpi-label]', `KPI label for ${code}`);
      const category = readText(row, '[data-kpi-category]', `Category for ${label}`);
      const sourceKind = row.querySelector('[data-kpi-source-kind]').value;
      const direction = row.querySelector('[data-kpi-direction]').value;
      const type = readText(row, '[data-kpi-type]', `Type for ${label}`);
      const formula = readText(row, '[data-kpi-formula]', `Formula for ${label}`);
      const originalFormula = String(metric.calculation?.formula || '').trim();
      const storedDenominator = String(metric.calculation?.denominator || '').trim();
      const denominator = formula.trim() === originalFormula && storedDenominator ? storedDenominator : deriveDenominator(formula);
      const filters = parseFilters(row, label);
      const calculation = {...(metric.calculation || {}), source_kind: sourceKind, formula, filters, denominator};
      if (formula.trim() === totalPacketLossFormula) calculation.totalpacketlost = totalPacketLossExpression;
      else delete calculation.totalpacketlost;

      metric.code = code;
      metric.kpi = label;
      metric.category = category;
      metric.source_kind = sourceKind;
      metric.direction = direction;
      metric.kpi_type = type;
      metric.calculation = calculation;
      metric.contexts = metric.contexts || {};
      metric.contexts[environment] = metric.contexts[environment] || {};
      const context = metric.contexts[environment];
      context.max_points = readNumeric(row, '[data-max-points]', `Maximum points for ${label}`);
      context.thresholds = context.thresholds || {};
      const thresholds = {};
      for (const key of ['low', 'medium', 'high']) {
        thresholds[key] = readNumeric(row, `[data-threshold="${key}"]`, `${key} threshold for ${label}`);
      }
      const monotonic = direction === 'higher_is_better'
        ? thresholds.low <= thresholds.medium && thresholds.medium <= thresholds.high
        : thresholds.low >= thresholds.medium && thresholds.medium >= thresholds.high;
      if (!monotonic) {
        throw new Error(`${label} thresholds must follow the selected direction: low, medium and high must move in KPI quality order.`);
      }
      context.thresholds = {...context.thresholds, ...thresholds};
      const ultraMode = row.querySelector('[data-ultra-mode]').value;
      if (ultraMode === 'none') {
        context.thresholds.ultra = null;
      } else if (ultraMode === 'fixed') {
        const ultraValue = readNumeric(row, '[data-ultra-value]', `Ultra threshold for ${label}`);
        if (direction === 'higher_is_better' && ultraValue < thresholds.high) {
          throw new Error(`${label} Ultra threshold must be at least its high threshold for the selected direction.`);
        }
        if (direction === 'lower_is_better' && ultraValue > thresholds.high) {
          throw new Error(`${label} Ultra threshold must be at most its high threshold for the selected direction.`);
        }
        context.thresholds.ultra = ultraValue;
      } else {
        const expectedUltraMode = direction === 'higher_is_better' ? 'best_max' : 'best_min';
        if (ultraMode !== expectedUltraMode) {
          throw new Error(`${label} Ultra rule must match the selected direction. Choose ${expectedUltraMode === 'best_max' ? 'Best maximum' : 'Best minimum'}, Fixed value or None.`);
        }
        const previousUltra = context.thresholds.ultra;
        context.thresholds.ultra = {
          rule: ultraMode,
          ...(previousUltra && typeof previousUltra === 'object' && previousUltra.source_formula
            ? {source_formula: previousUltra.source_formula} : {}),
        };
      }
      context.score_mapping = context.score_mapping || {};
      anchors.forEach(([key, anchorLabel]) => {
        context.score_mapping[key] = readNumeric(row, `[data-score-anchor="${key}"]`, `${anchorLabel} score interpolation anchor for ${label}`) / 100;
      });
      return {row, metric, originalCode, originalIndex: Number(row.dataset.orderIndex), newCode: code};
    });

    const sharesByEnvironment = new Map(environmentKeys().map((environment) => [
      environment, environmentWeightShares(environment, rows).shares,
    ]));
    entries.forEach(({row, metric}, index) => {
      const validEnvironments = new Set(environmentKeys());
      metric.contexts = Object.fromEntries(Object.entries(metric.contexts || {}).filter(([key]) => validEnvironments.has(key)));
      environmentKeys().forEach((environment) => {
        metric.contexts[environment] = metric.contexts[environment] || {};
        metric.contexts[environment].max_points = pointsForRow(row, environment);
        metric.contexts[environment].weight_share = sharesByEnvironment.get(environment)?.[index] || 0;
        if (environment !== environmentSelect.value) applyCachedContextDraft(metric, row, environment, metric.kpi || metric.code, metric.direction);
      });
      environmentKeys().forEach((environment) => {
        const thresholds = metric.contexts[environment]?.thresholds || {};
        const values = ['low', 'medium', 'high'].map((key) => Number(thresholds[key]));
        const monotonic = values.every(Number.isFinite) && (metric.direction === 'higher_is_better'
          ? values[0] <= values[1] && values[1] <= values[2]
          : values[0] >= values[1] && values[1] >= values[2]);
        if (!monotonic) {
          throw new Error(`${metric.kpi || metric.code} thresholds in ${environmentLabel(environment)} must follow the selected direction. Switch environments to update each threshold set before saving.`);
        }
        const ultra = thresholds.ultra;
        if (ultra && typeof ultra === 'object') {
          const expectedRule = metric.direction === 'higher_is_better' ? 'best_max' : 'best_min';
          if (ultra.rule !== expectedRule) {
            throw new Error(`${metric.kpi || metric.code} Ultra rule in ${environmentLabel(environment)} must match the selected direction. Switch environments to update each Ultra rule before saving.`);
          }
        } else if (typeof ultra === 'number') {
          const comparisonIsValid = metric.direction === 'higher_is_better' ? ultra >= values[2] : ultra <= values[2];
          if (!comparisonIsValid) {
            throw new Error(`${metric.kpi || metric.code} Ultra threshold in ${environmentLabel(environment)} must match the selected direction. Switch environments to update each Ultra threshold before saving.`);
          }
        }
      });
    });

    const uniqueCodes = new Set(entries.map((entry) => entry.newCode.toLocaleLowerCase()));
    if (uniqueCodes.size !== entries.length) throw new Error('KPI codes must be unique within a scoring methodology.');
    const codeMap = new Map(entries.filter((entry) => entry.originalCode).map((entry) => [entry.originalCode, entry.newCode]));
    const submittedMetrics = entries
      .sort((left, right) => left.originalIndex - right.originalIndex)
      .map((entry) => entry.metric);
    const submittedCodes = new Set(submittedMetrics.map((metric) => metric.code));
    let priorityCodes = latestConfiguration.gap_priority || [];
    if (priorityDirty) priorityCodes = Array.from(priorityRows.querySelectorAll('tr[data-kpi-code]'), (row) => row.dataset.kpiCode);
    latestConfiguration.gap_priority = [...new Set(priorityCodes.map((code) => codeMap.get(code) || code))]
      .filter((code) => submittedCodes.has(code));
    latestConfiguration.metrics = submittedMetrics;
    latestConfiguration.next_kpi_number = normalizeNextKpiNumber({
      ...latestConfiguration,
      next_kpi_number: Math.max(nextKpiNumber, Number(latestConfiguration.next_kpi_number) || 1),
      metrics: submittedMetrics,
    });
    return latestConfiguration;
  };

  const saveKpis = async () => {
    const profileId = activeProfileId;
    const environment = environmentSelect.value;
    setStatus(kpiStatus, 'Saving KPI configuration…');
    if (kpiSave) kpiSave.disabled = true;
    try {
      await saveConfiguration((latest) => readKpiRows(latest, environment), profileId);
      kpiDirty = false;
      priorityDirty = false;
      render();
      setStatus(kpiStatus, 'KPI configuration saved.', 'success');
    } catch (error) {
      setStatus(kpiStatus, error.message || 'Unable to save KPI configuration.', 'error');
    } finally {
      if (kpiSave) kpiSave.disabled = false;
    }
  };

  const savePriority = async () => {
    const profileId = activeProfileId;
    setStatus(priorityStatus, 'Saving GAP KPI priority…');
    if (prioritySave) prioritySave.disabled = true;
    try {
      const codes = Array.from(priorityRows.querySelectorAll('tr[data-kpi-code]'), (row) => row.dataset.kpiCode);
      await saveConfiguration((latest) => {
        latest.gap_priority = [...codes];
        return latest;
      }, profileId);
      priorityDirty = false;
      renderPriorityRows();
      setStatus(priorityStatus, 'GAP KPI priority saved.', 'success');
    } catch (error) {
      setStatus(priorityStatus, error.message || 'Unable to save GAP KPI priority.', 'error');
    } finally {
      if (prioritySave) prioritySave.disabled = false;
    }
  };

  const saveHierarchy = async () => {
    const profileId = activeProfileId;
    const levels = Array.from(hierarchyRows.querySelectorAll('tr[data-aggregation-level]'), (row) => row.dataset.aggregationLevel);
    if (levels.length !== defaultHierarchy.length
        || new Set(levels).size !== defaultHierarchy.length
        || levels.some((level) => !hierarchyDimensions.has(level))) {
      setStatus(hierarchyStatus, 'The aggregation hierarchy must contain each dimension exactly once.', 'error');
      return;
    }
    setStatus(hierarchyStatus, 'Saving scoring aggregation hierarchy…');
    if (hierarchySave) hierarchySave.disabled = true;
    try {
      await saveConfiguration((latest) => {
        latest.aggregation_hierarchy = [...levels];
        return latest;
      }, profileId);
      hierarchyDirty = false;
      hierarchyOrder = [...levels];
      renderHierarchyRows();
      setStatus(hierarchyStatus, 'Scoring aggregation hierarchy saved.', 'success');
    } catch (error) {
      setStatus(hierarchyStatus, error.message || 'Unable to save scoring aggregation hierarchy.', 'error');
    } finally {
      if (hierarchySave) hierarchySave.disabled = false;
    }
  };

  const hasUnsavedChanges = () => kpiDirty || priorityDirty || hierarchyDirty;

  const discardUnsavedChanges = () => {
    kpiDirty = false;
    priorityDirty = false;
    hierarchyDirty = false;
  };

  const confirmProfileChange = async () => {
    if (!hasUnsavedChanges()) return true;
    const accepted = await openProfileDialog({
      title: 'Discard unsaved changes?',
      description: 'Unsaved scoring methodology changes will be discarded.',
      confirmLabel: 'Discard changes',
    });
    if (!accepted) return false;
    discardUnsavedChanges();
    return true;
  };

  const profileNameIsAvailable = (name, exceptId = '') => !profileCollection.profiles.some(
    (profile) => profile.id !== exceptId && profile.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase(),
  );

  const environmentNameIsAvailable = (name, exceptKey = '') => !environmentEntries().some(
    ([key]) => key !== exceptKey && key.trim().toLocaleLowerCase() === name.toLocaleLowerCase(),
  );

  const closeProfileDialog = (result) => {
    if (!profileDialog) return;
    profileDialog.hidden = true;
    document.body.classList.remove('loading-active');
    window.removeEventListener('keydown', handleProfileDialogKeydown);
    const resolve = profileDialogResolver;
    profileDialogResolver = null;
    profileDialogOptions = null;
    resolve?.(result);
  };

  const handleProfileDialogKeydown = (event) => {
    if (event.key === 'Escape' && profileDialog && !profileDialog.hidden) {
      event.preventDefault();
      closeProfileDialog(null);
    }
  };

  const openProfileDialog = ({title, description, confirmLabel = 'Continue', initialValue = '', nameRequired = false, exceptId = '', distribution = false, environmentCreate = false, environmentRename = false, exceptEnvironmentKey = '', initialG1 = '', initialG2 = ''}) => {
    if (!profileDialog || !profileDialogTitle || !profileDialogCopy || !profileDialogConfirm || !profileDialogCancel) {
      return Promise.resolve(null);
    }
    if (profileDialogResolver) closeProfileDialog(null);
    profileDialogOptions = {nameRequired, exceptId, distribution, environmentCreate, environmentRename, exceptEnvironmentKey};
    if (profileDialogEyebrow) profileDialogEyebrow.textContent = environmentCreate || environmentRename
      ? 'Scoring environment' : 'Scoring methodology';
    profileDialogTitle.textContent = title;
    profileDialogCopy.textContent = description;
    profileDialogConfirm.textContent = confirmLabel;
    if (profileDialogNameField) profileDialogNameField.hidden = !nameRequired;
    if (profileDialogDistribution) profileDialogDistribution.hidden = !distribution;
    if (profileDialogEnvironmentFields) profileDialogEnvironmentFields.hidden = !environmentCreate;
    if (profileDialogNameLabel) profileDialogNameLabel.textContent = environmentCreate || environmentRename ? 'Environment name' : 'Methodology name';
    if (profileDialogTotalLabel) profileDialogTotalLabel.textContent = environmentCreate ? 'New environment total points' : 'Selected environment total points';
    if (profileDialogTotal) profileDialogTotal.setAttribute('aria-label', environmentCreate
      ? 'New environment total points' : `Total points for ${environmentLabel(environmentSelect.value)}`);
    if (profileDialogName) {
      profileDialogName.value = initialValue;
      profileDialogName.required = nameRequired;
    }
    if (distribution && profileDialogReference) {
      profileDialogReference.replaceChildren();
      environmentEntries().forEach(([key]) => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = environmentLabel(key);
        option.selected = key === environmentSelect.value;
        profileDialogReference.append(option);
      });
      if (profileDialogTotal) profileDialogTotal.value = environmentTotalFor(environmentSelect.value).toFixed(2);
    }
    if (profileDialogG1) {
      profileDialogG1.value = initialG1 || (environmentCreate ? initialValue : '');
      profileDialogG1.dataset.manuallyEdited = 'false';
    }
    if (profileDialogG2) profileDialogG2.value = initialG2;
    if (profileDialogTotal) profileDialogTotal.required = distribution;
    if (profileDialogError) profileDialogError.textContent = '';
    profileDialog.hidden = false;
    document.body.classList.add('loading-active');
    return new Promise((resolve) => {
      profileDialogResolver = resolve;
      window.addEventListener('keydown', handleProfileDialogKeydown);
      window.requestAnimationFrame(() => {
        if (nameRequired) profileDialogName?.focus();
        else profileDialogConfirm.focus();
      });
    });
  };

  profileDialogCancel?.addEventListener('click', () => closeProfileDialog(null));
  profileDialog?.addEventListener('click', (event) => {
    if (event.target === profileDialog) closeProfileDialog(null);
  });
  profileDialogConfirm?.addEventListener('click', () => {
    if (profileDialogOptions?.distribution) {
      const total = Number(profileDialogTotal?.value);
      if (!profileDialogReference?.value || !profileDialogTotal?.value.trim()
          || !Number.isFinite(total) || total < 0 || !profileDialogTotal.checkValidity()) {
        if (profileDialogError) profileDialogError.textContent = 'Choose a reference environment and enter a finite, non-negative points total.';
        profileDialogTotal?.focus();
        return;
      }
      if (profileDialogOptions.environmentCreate) {
        const name = profileDialogName?.value.trim() || '';
        const g1 = profileDialogG1?.value.trim() || '';
        const g2 = profileDialogG2?.value.trim() || '';
        let error = '';
        if (!name || name.length > 80) error = 'Environment name must contain 1 to 80 characters.';
        else if (!environmentNameIsAvailable(name)) error = 'An environment with that name already exists.';
        else if (!g1) error = 'Source G_Level_1 is required.';
        else if (g1.length > 160 || g2.length > 160) error = 'Source selectors must be 160 characters or fewer.';
        else if (environmentEntries().some(([, environment]) => {
          const otherG1 = String(environment.g_level_1 || '').trim().toLocaleLowerCase();
          const otherG2 = String(environment.g_level_2 || '').trim().toLocaleLowerCase();
          return otherG1 === g1.toLocaleLowerCase() && (!otherG2 || !g2 || otherG2 === g2.toLocaleLowerCase());
        })) error = 'The source selector overlaps another environment. Use a unique G_Level_1 or G_Level_2 combination.';
        if (error) {
          if (profileDialogError) profileDialogError.textContent = error;
          if (error.startsWith('Environment name') || error.startsWith('An environment')) profileDialogName?.focus();
          else profileDialogG1?.focus();
          return;
        }
        closeProfileDialog({name, g1, g2, referenceEnvironment: profileDialogReference.value, totalPoints: total});
        return;
      }
      closeProfileDialog({referenceEnvironment: profileDialogReference.value, totalPoints: total});
      return;
    }
    if (!profileDialogOptions?.nameRequired) {
      closeProfileDialog(true);
      return;
    }
    const name = profileDialogName?.value.trim() || '';
    if (profileDialogOptions.environmentRename) {
      let environmentError = '';
      if (!name || name.length > 80) environmentError = 'Environment name must contain 1 to 80 characters.';
      else if (name.toLocaleLowerCase() === 'combined') environmentError = 'Environment name cannot be Combined.';
      else if (!environmentNameIsAvailable(name, profileDialogOptions.exceptEnvironmentKey)) environmentError = 'An environment with that name already exists.';
      if (environmentError) {
        if (profileDialogError) profileDialogError.textContent = environmentError;
        profileDialogName?.focus();
        return;
      }
      closeProfileDialog(name);
      return;
    }
    let error = '';
    if (!name || name.length > 80) error = 'Methodology name must contain 1 to 80 characters.';
    else if (!profileNameIsAvailable(name, profileDialogOptions.exceptId)) error = 'A scoring methodology with that name already exists.';
    if (error) {
      if (profileDialogError) profileDialogError.textContent = error;
      profileDialogName?.focus();
      return;
    }
    closeProfileDialog(name);
  });
  profileDialogName?.addEventListener('input', () => {
    if (profileDialogError) profileDialogError.textContent = '';
    if (profileDialogOptions?.environmentCreate && profileDialogG1?.dataset.manuallyEdited !== 'true') {
      profileDialogG1.value = profileDialogName.value;
    }
  });
  profileDialogG1?.addEventListener('input', () => {
    profileDialogG1.dataset.manuallyEdited = 'true';
    if (profileDialogError) profileDialogError.textContent = '';
  });

  const createProfileId = () => window.crypto?.randomUUID?.()
    || `methodology-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  const setProfileControlsDisabled = (disabled) => {
    if (profileSelect) profileSelect.disabled = disabled || !profileCollection?.profiles?.length;
    profileActions.forEach((button) => {
      button.disabled = disabled || !currentProfile()
        || (button.dataset.scoringProfileAction === 'delete' && profileCollection.profiles.length <= 1);
    });
  };

  const runProfileAction = async (action) => {
    setProfileControlsDisabled(true);
    try {
      if (!await confirmProfileChange()) return;
      const active = currentProfile();
      let requestedName = null;
      if (action === 'create') requestedName = await openProfileDialog({
        title: 'Create scoring methodology', description: 'Choose a unique name. The new methodology will become active.',
        confirmLabel: 'Create', initialValue: 'New methodology', nameRequired: true,
      });
      if (action === 'copy') requestedName = await openProfileDialog({
        title: 'Copy scoring methodology', description: 'Choose a unique name. The copy will become active.',
        confirmLabel: 'Copy', initialValue: `${active?.name || 'Scoring methodology'} copy`, nameRequired: true,
      });
      if (action === 'rename') requestedName = await openProfileDialog({
        title: 'Rename scoring methodology', description: 'Choose a unique name for this methodology.',
        confirmLabel: 'Rename', initialValue: active?.name || '', nameRequired: true, exceptId: active?.id || '',
      });
      if (['create', 'copy', 'rename'].includes(action) && requestedName === null) return;
      if (action === 'delete') {
        if ((profileCollection?.profiles?.length || 0) <= 1) {
          setStatus(kpiStatus, 'Keep at least one scoring methodology in this workspace.', 'error');
          return;
        }
        const confirmed = await openProfileDialog({
          title: 'Delete scoring methodology?',
          description: `Delete “${active?.name || 'Scoring methodology'}”? Future scoring jobs will no longer use this profile.`,
          confirmLabel: 'Delete',
        });
        if (!confirmed) return;
      }

      await enqueueProfileUpdate((latest) => {
        const source = latest.profiles.find((profile) => profile.id === latest.active_profile_id);
        if (!source) throw new Error('The active scoring methodology is no longer available.');
        if (action === 'rename') {
          const target = latest.profiles.find((profile) => profile.id === source.id);
          target.name = requestedName;
        } else if (action === 'delete') {
          latest.profiles = latest.profiles.filter((profile) => profile.id !== source.id);
          latest.active_profile_id = latest.profiles[0].id;
        } else {
          const id = createProfileId();
          latest.profiles.push({id, name: requestedName, configuration: clone(source.configuration)});
          latest.active_profile_id = id;
        }
        return latest;
      });
      discardUnsavedChanges();
      render();
      setStatus(kpiStatus, action === 'delete' ? 'Scoring methodology deleted.' : `Scoring methodology ${action === 'rename' ? 'renamed' : action === 'copy' ? 'copied' : 'created'}.`, 'success');
    } catch (error) {
      renderProfileControls();
      setStatus(kpiStatus, error.message || 'Unable to update scoring methodology.', 'error');
    } finally {
      setProfileControlsDisabled(false);
    }
  };

  const activateProfile = async (profileId) => {
    if (profileId === activeProfileId || !profileCollection?.profiles?.some((profile) => profile.id === profileId)) return;
    setProfileControlsDisabled(true);
    if (!await confirmProfileChange()) {
      if (profileSelect) profileSelect.value = activeProfileId;
      setProfileControlsDisabled(false);
      return;
    }
    setStatus(kpiStatus, 'Activating scoring methodology…');
    try {
      await enqueueProfileUpdate((latest) => {
        if (!latest.profiles.some((profile) => profile.id === profileId)) throw new Error('The selected scoring methodology is no longer available.');
        latest.active_profile_id = profileId;
        return latest;
      });
      render();
      setStatus(kpiStatus, `Active methodology: ${currentProfile()?.name || 'Scoring methodology'}.`, 'success');
    } catch (error) {
      renderProfileControls();
      setStatus(kpiStatus, error.message || 'Unable to activate scoring methodology.', 'error');
    } finally {
      setProfileControlsDisabled(false);
    }
  };

  const makeNewMetric = (category = 'Custom') => {
    const existing = configuration?.metrics || [];
    const template = existing.find((metric) => metric.source_kind === 'data') || existing[0];
    if (!template) throw new Error('Add at least one KPI before creating a new scoring methodology.');
    const visibleCodes = rowMetrics().map((row) => row.querySelector('[data-kpi-code-input]')?.value.trim());
    nextKpiNumber = Math.max(nextKpiNumber, normalizeNextKpiNumber({
      next_kpi_number: nextKpiNumber,
      metrics: [...existing, ...visibleCodes.filter(Boolean).map((code) => ({code}))],
    }));
    const metric = clone(template);
    metric.code = `K${nextKpiNumber}`;
    nextKpiNumber += 1;
    metric.kpi = 'New KPI';
    metric.category = category;
    metric.kpi_type = template.kpi_type || 'Reliable';
    environmentKeys().forEach((environment) => {
      metric.contexts[environment] = metric.contexts[environment] || {};
      metric.contexts[environment].max_points = 0;
      metric.contexts[environment].weight_share = 0;
    });
    delete metric.validation_examples;
    delete metric.sources;
    delete metric.gap_example;
    return metric;
  };

  const addKpi = (afterRow = null) => {
    try {
      const category = afterRow?.querySelector('[data-kpi-category]')?.value.trim() || 'Custom';
      const metric = makeNewMetric(afterRow ? category : 'Custom');
      const orderedRows = rowMetrics().sort((left, right) => Number(left.dataset.orderIndex) - Number(right.dataset.orderIndex));
      const insertionIndex = afterRow ? Math.max(0, orderedRows.indexOf(afterRow) + 1) : orderedRows.length;
      const index = afterRow ? insertionIndex : Math.max(0, ...orderedRows.map((row) => Number(row.dataset.orderIndex) + 1));
      const row = renderKpiRow(metric, index, {newMetric: true});
      if (!row) throw new Error('Unable to create the KPI row.');
      if (afterRow) {
        orderedRows.splice(insertionIndex, 0, row);
        orderedRows.forEach((item, orderIndex) => { item.dataset.orderIndex = String(orderIndex); });
      }
      kpiRows.append(row);
      renderCategoryGroups();
      refreshKpiActionButtons();
      syncWeightMode();
      updateDerivedWeights();
      row.querySelector('[data-kpi-label]')?.focus();
      kpiDirty = true;
      setStatus(kpiStatus, 'Unsaved KPI changes. Complete the new KPI formula and filters before saving.');
    } catch (error) {
      setStatus(kpiStatus, error.message || 'Unable to add KPI.', 'error');
    }
  };

  const moveKpiWithinCategory = (row, direction) => {
    const category = row.querySelector('[data-kpi-category]')?.value.trim() || 'Other';
    const peers = rowMetrics()
      .filter((item) => (item.querySelector('[data-kpi-category]')?.value.trim() || 'Other') === category)
      .sort((left, right) => Number(left.dataset.orderIndex) - Number(right.dataset.orderIndex));
    const index = peers.indexOf(row);
    const neighbor = peers[index + (direction === 'up' ? -1 : 1)];
    if (!neighbor) return;
    const currentOrder = row.dataset.orderIndex;
    row.dataset.orderIndex = neighbor.dataset.orderIndex;
    neighbor.dataset.orderIndex = currentOrder;
    renderCategoryGroups();
    kpiDirty = true;
    setStatus(kpiStatus, 'Unsaved KPI order changes. KPI order is preserved when saved.');
  };

  const applyWeightEdit = (editedInput) => {
    const row = editedInput.closest('tr[data-kpi-code]');
    const targetPercent = Number(editedInput.value);
    const environment = environmentSelect.value;
    const rows = rowMetrics();
    const selectedTotal = environmentTotalFor(environment, rows);
    if (!editedInput.value.trim() || !Number.isFinite(targetPercent) || targetPercent < 0 || targetPercent > 100) {
      editedInput.setAttribute('aria-invalid', 'true');
      return 'Enter a weight between 0% and 100% for this environment.';
    }
    const rowIndex = rows.indexOf(row);
    const currentShares = environmentWeightShares(environment, rows).shares;
    const peerRows = rows.filter((item) => item !== row);
    const remainingPercent = Math.max(0, 100 - targetPercent);
    if (!peerRows.length && remainingPercent > 0.000001) {
      editedInput.setAttribute('aria-invalid', 'true');
      return 'A scoring environment with one KPI must assign it 100% weight.';
    }
    const peerPoints = peerRows.map((item) => pointsForRow(item, environment));
    const peerTotal = peerPoints.reduce((sum, value) => sum + value, 0);
    const storedPeerShares = normalizeShares(peerRows.map((item) => currentShares[rows.indexOf(item)] || 0));
    const peerShares = peerTotal > 0
      ? peerPoints.map((points) => points / peerTotal)
      : storedPeerShares.length ? storedPeerShares : peerRows.map(() => 1 / Math.max(peerRows.length, 1));
    const nextShares = rows.map((_item, index) => index === rowIndex ? targetPercent / 100 : 0);
    peerRows.forEach((item, index) => {
      nextShares[rows.indexOf(item)] = remainingPercent / 100 * peerShares[index];
    });
    rows.forEach((item, index) => setRowEnvironmentShare(item, environment, nextShares[index]));
    if (selectedTotal > 0) {
      const targetPoints = selectedTotal * targetPercent / 100;
      row.querySelector('[data-max-points]').value = String(targetPoints);
      peerRows.forEach((item, index) => {
        setRowEnvironmentPoints(item, environment, selectedTotal * nextShares[rows.indexOf(item)]);
      });
    }
    editedInput.removeAttribute('aria-invalid');
    updateDerivedWeights();
    return '';
  };

  const applyEnvironmentPointsEdit = (input) => {
    const environment = environmentSelect.value;
    const rows = rowMetrics();
    const requestedTotal = Number(input.value);
    if (!input.value.trim() || !Number.isFinite(requestedTotal) || requestedTotal < 0) {
      input.setAttribute('aria-invalid', 'true');
      return 'Enter a valid non-negative environment total.';
    }
    const previousTotal = environmentTotalFor(environment, rows);
    const distribution = environmentWeightShares(environment, rows);
    rows.forEach((row, index) => setRowEnvironmentShare(row, environment, distribution.shares[index] || 0));
    rows.forEach((row, index) => setRowEnvironmentPoints(row, environment, requestedTotal * (distribution.shares[index] || 0)));
    input.removeAttribute('aria-invalid');
    updateDerivedWeights();
    if (previousTotal <= 0 && requestedTotal > 0) {
      if (distribution.source === 'equal') return `${environmentLabel(environment)} had no saved KPI weights; points were distributed equally.`;
      if (distribution.source === 'city') return `${environmentLabel(environment)} had no saved KPI weights; points use the available base environment weights.`;
      return `${environmentLabel(environment)} had 0 points; points were distributed using its saved KPI weights.`;
    }
    if (requestedTotal === 0) return `${environmentLabel(environment)} has 0 points; its relative KPI weights are retained.`;
    return '';
  };

  const applyEnvironmentWeightEdit = (input) => {
    const environment = environmentSelect.value;
    const rows = rowMetrics();
    const targetPercent = Number(input.value);
    const currentGlobalTotal = globalPointsTotal(rows);
    if (!input.value.trim() || !Number.isFinite(targetPercent) || targetPercent < 0 || targetPercent > 100) {
      input.setAttribute('aria-invalid', 'true');
      return 'Enter an environment weight between 0% and 100%.';
    }
    if (currentGlobalTotal <= 0) {
      input.setAttribute('aria-invalid', 'true');
      return 'Add environment points in Points mode before editing global environment weights.';
    }

    const environments = environmentKeys();
    const currentTotals = new Map(environments.map((key) => [key, environmentTotalFor(key, rows)]));
    const distributions = new Map(environments.map((key) => [key, environmentWeightShares(key, rows)]));
    const otherEnvironments = environments.filter((key) => key !== environment);
    const targetPoints = currentGlobalTotal * targetPercent / 100;
    const remainingPoints = currentGlobalTotal - targetPoints;
    const otherCurrentTotal = otherEnvironments.reduce((sum, key) => sum + currentTotals.get(key), 0);
    let otherShares = otherEnvironments.map((key) => otherCurrentTotal > 0
      ? currentTotals.get(key) / otherCurrentTotal
      : Number(configuration.scope.environments[key]?.weight_share) || 0);
    let normalizedOtherShares = normalizeShares(otherShares);
    if (!normalizedOtherShares.length) normalizedOtherShares = otherEnvironments.map(() => 1 / Math.max(otherEnvironments.length, 1));
    const source = distributions.get(environment)?.source || 'equal';

    environments.forEach((key, environmentIndex) => {
      const pointsTotal = key === environment
        ? targetPoints
        : remainingPoints * normalizedOtherShares[otherEnvironments.indexOf(key)];
      const shares = distributions.get(key)?.shares || [];
      rows.forEach((row, rowIndex) => {
        setRowEnvironmentShare(row, key, shares[rowIndex] || 0);
        setRowEnvironmentPoints(row, key, pointsTotal * (shares[rowIndex] || 0));
      });
    });
    input.removeAttribute('aria-invalid');
    updateDerivedWeights();
    if (currentTotals.get(environment) <= 0 && targetPoints > 0) {
      if (source === 'equal') return `${environmentLabel(environment)} had no saved KPI weights; points were distributed equally.`;
      if (source === 'city') return `${environmentLabel(environment)} had no saved KPI weights; points use the available base environment weights.`;
      return `${environmentLabel(environment)} had 0 points; points were distributed using its saved KPI weights.`;
    }
    return '';
  };

  const distributeEnvironmentPoints = async () => {
    const selection = await openProfileDialog({
      title: 'Distribute environment points',
      description: `Set ${environmentLabel(environmentSelect.value)} points using the KPI weight distribution from a reference environment.`,
      confirmLabel: 'Distribute points',
      distribution: true,
    });
    if (!selection) return;
    const rows = rowMetrics();
    const distribution = environmentWeightShares(selection.referenceEnvironment, rows);
    const allocatedPoints = scoringConfigMath.allocatePoints(selection.totalPoints, distribution.shares);
    rows.forEach((row, index) => {
      const share = distribution.shares[index] || 0;
      setRowEnvironmentShare(row, environmentSelect.value, share);
      setRowEnvironmentPoints(row, environmentSelect.value, allocatedPoints[index] || 0);
    });
    updateDerivedWeights();
    kpiDirty = true;
    if (selection.totalPoints <= 0) {
      setStatus(kpiStatus, `${environmentLabel(environmentSelect.value)} is set to 0 points; its relative KPI weights are retained.`);
    } else if (distribution.source === 'equal') {
      setStatus(kpiStatus, 'No saved reference weights were available; points were distributed equally. Save the KPI configuration to apply this draft.');
    } else if (distribution.source === 'city') {
      setStatus(kpiStatus, 'No saved reference weights were available; points use the base environment distribution. Save the KPI configuration to apply this draft.');
    } else {
      setStatus(kpiStatus, `Unsaved KPI changes. ${environmentLabel(environmentSelect.value)} points now follow ${environmentLabel(selection.referenceEnvironment)} relative weights.`);
    }
  };

  const contextToDraft = (context = {}) => {
    const ultra = context.thresholds?.ultra;
    const ultraMode = ultra === null || ultra === undefined ? 'none' : typeof ultra === 'object' ? String(ultra.rule || 'none') : 'fixed';
    return {
      max_points: String(context.max_points ?? 0),
      thresholds: Object.fromEntries(['low', 'medium', 'high'].map((key) => [key, String(context.thresholds?.[key] ?? '')])),
      ultra_mode: ultraMode,
      ultra_value: typeof ultra === 'number' ? String(ultra) : '',
      score_mapping: Object.fromEntries(anchors.map(([key]) => [key, String(Number(context.score_mapping?.[key]) * 100)])),
      weight_share: Number(context.weight_share) || 0,
    };
  };

  const createEnvironment = async () => {
    if (!configuration || environmentKeys().length >= 32) {
      setStatus(kpiStatus, 'A scoring methodology can contain up to 32 environments.', 'error');
      return;
    }
    rowMetrics().forEach(captureSelectedContext);
    const result = await openProfileDialog({
      title: 'Create scoring environment',
      description: 'Choose a name, source selector, and reference environment. KPI thresholds and score mappings follow the reference environment; points follow its relative KPI weights.',
      confirmLabel: 'Create environment',
      initialValue: 'New environment',
      nameRequired: true,
      distribution: true,
      environmentCreate: true,
    });
    if (!result) return;

    const rows = rowMetrics();
    const reference = result.referenceEnvironment;
    const distribution = environmentWeightShares(reference, rows);
    const newKey = result.name.trim();
    const scope = clone(configuration.scope || {});
    scope.environments = {...(scope.environments || {}), [newKey]: {
      sheet: newKey,
      g_level_1: result.g1.trim(),
      ...(result.g2.trim() ? {g_level_2: result.g2.trim()} : {}),
    }};
    try {
      applyEnvironmentMapping(scope);
      const allocatedPoints = scoringConfigMath.allocatePoints(result.totalPoints, distribution.shares);
      const contexts = rows.map((row, index) => {
        const base = clone(metricForRow(row) || row._newMetricTemplate || {});
        applyCachedContextDraft(base, row, reference, base.kpi || base.code, base.direction || 'higher_is_better');
        const context = clone(base.contexts?.[reference] || {});
        const share = distribution.shares[index] || 0;
        context.max_points = allocatedPoints[index] || 0;
        context.weight_share = share;
        return {row, context, share};
      });
      configuration.scope = scope;
      contexts.forEach(({row, context, share}) => {
        row._contextDrafts = {...row._contextDrafts, [newKey]: contextToDraft(context)};
        row._contextPointDrafts = {...row._contextPointDrafts, [newKey]: context.max_points};
        row._weightShareDrafts = {...row._weightShareDrafts, [newKey]: share};
        const metric = configuration.metrics?.find((item) => item.code === row.dataset.originalCode) || row._newMetricTemplate;
        if (metric) metric.contexts[newKey] = clone(context);
      });
      renderEnvironmentOptions();
      environmentSelect.value = newKey;
      lastEnvironment = newKey;
      syncEnvironmentSourceFields();
      rowMetrics().forEach((row) => hydrateSelectedContext(row, newKey));
      syncWeightMode();
      updateDerivedWeights();
      kpiDirty = true;
      setStatus(kpiStatus, result.totalPoints === 0
        ? `Unsaved environment “${newKey}” created with 0 points. Its reference KPI weights are retained.`
        : `Unsaved environment “${newKey}” created using ${environmentLabel(reference)} KPI settings. Save to apply the new environment.`, 'success');
    } catch (error) {
      renderEnvironmentOptions();
      setStatus(kpiStatus, error.message || 'Unable to create the scoring environment.', 'error');
    }
  };

  const deleteEnvironment = async () => {
    const environment = environmentSelect.value;
    const keys = environmentKeys();
    if (keys.length <= 1) {
      setStatus(kpiStatus, 'Keep at least one scoring environment in this methodology.', 'error');
      return;
    }
    rowMetrics().forEach(captureSelectedContext);
    const remainingTotal = globalPointsTotal() - environmentTotalFor(environment);
    if (remainingTotal <= 0) {
      setStatus(kpiStatus, 'Deleting this environment would leave the methodology with 0 points. Keep at least one environment with points.', 'error');
      return;
    }
    const confirmed = await openProfileDialog({
      title: 'Delete scoring environment?',
      description: `Delete “${environmentLabel(environment)}” and its KPI points, thresholds, and mappings from this methodology?`,
      confirmLabel: 'Delete environment',
    });
    if (!confirmed) return;
    delete configuration.scope.environments[environment];
    configuration.scope.environment_mapping = Object.fromEntries(
      Object.entries(configuration.scope.environment_mapping || {}).filter(([, target]) => target !== environment),
    );
    rowMetrics().forEach((row) => {
      delete row._contextDrafts?.[environment];
      delete row._contextPointDrafts?.[environment];
      delete row._weightShareDrafts?.[environment];
      const metric = configuration.metrics?.find((item) => item.code === row.dataset.originalCode) || row._newMetricTemplate;
      if (metric) delete metric.contexts[environment];
    });
    const remainingEnvironment = environmentKeys()[0];
    renderEnvironmentOptions();
    environmentSelect.value = remainingEnvironment;
    lastEnvironment = remainingEnvironment;
    rowMetrics().forEach((row) => hydrateSelectedContext(row, remainingEnvironment));
    syncEnvironmentSourceFields();
    syncWeightMode();
    updateDerivedWeights();
    kpiDirty = true;
    setStatus(kpiStatus, `Unsaved environment “${environmentLabel(environment)}” deletion. Save to apply the change.`);
  };

  const renameEnvironment = async () => {
    const previousName = environmentSelect.value;
    const previousLabel = environmentLabel(previousName);
    if (!configuration || !previousName) return;
    const requestedName = await openProfileDialog({
      title: 'Rename scoring environment',
      description: `Rename “${previousLabel}”. Its KPI points, thresholds, source selectors and saved allocations will stay with the environment.`,
      confirmLabel: 'Rename environment',
      initialValue: previousName,
      nameRequired: true,
      environmentRename: true,
      exceptEnvironmentKey: previousName,
    });
    if (!requestedName || requestedName === previousName) return;

    rowMetrics().forEach((row) => captureSelectedContext(row));
    const scope = clone(configuration.scope || {});
    const environments = scope.environments || {};
    if (!Object.prototype.hasOwnProperty.call(environments, previousName)
        || !environmentNameIsAvailable(requestedName, previousName)) {
      setStatus(kpiStatus, 'An environment with that name already exists or is no longer available.', 'error');
      return;
    }
    scope.environments = Object.fromEntries(Object.entries(environments).map(([key, environment]) => [
      key === previousName ? requestedName : key,
      key === previousName ? {...environment, display_name: requestedName} : environment,
    ]));
    applyEnvironmentMapping(scope);

    const metrics = new Set([
      ...(configuration.metrics || []),
      ...rowMetrics().map((row) => row._newMetricTemplate).filter(Boolean),
    ]);
    metrics.forEach((metric) => {
      const contexts = metric.contexts || {};
      if (Object.prototype.hasOwnProperty.call(contexts, previousName)) {
        metric.contexts = Object.fromEntries(Object.entries(contexts).map(([key, context]) => [
          key === previousName ? requestedName : key, context,
        ]));
      }
    });
    rowMetrics().forEach((row) => {
      for (const property of ['_contextDrafts', '_contextPointDrafts', '_weightShareDrafts']) {
        const drafts = row[property];
        if (!drafts || !Object.prototype.hasOwnProperty.call(drafts, previousName)) continue;
        row[property] = Object.fromEntries(Object.entries(drafts).map(([key, value]) => [
          key === previousName ? requestedName : key, value,
        ]));
      }
    });

    configuration.scope = scope;
    renderEnvironmentOptions();
    environmentSelect.value = requestedName;
    lastEnvironment = requestedName;
    rowMetrics().forEach((row) => hydrateSelectedContext(row, requestedName));
    syncEnvironmentSourceFields();
    syncWeightMode();
    updateDerivedWeights();
    kpiDirty = true;
    setStatus(kpiStatus, `Unsaved environment rename from “${previousLabel}” to “${requestedName}”. Save to apply the change.`, 'success');
  };

  const importButton = root.querySelector('[data-scoring-config-import]');
  const importFile = root.querySelector('[data-scoring-config-file]');
  importButton?.addEventListener('click', () => importFile?.click());
  importFile?.addEventListener('change', async () => {
    const file = importFile.files?.[0];
    if (!file) return;
    const importPrompt = hasUnsavedChanges()
      ? 'Discard unsaved scoring methodology changes and replace all scoring methodologies in this workspace with the selected JSON? Saved jobs retain their original rules.'
      : 'Replace all scoring methodologies in this workspace with the selected JSON? Saved jobs retain their original rules.';
    if (profileCollection && !await openProfileDialog({
      title: 'Replace scoring methodologies?', description: importPrompt, confirmLabel: 'Replace profiles',
    })) {
      importFile.value = '';
      return;
    }
    const body = new FormData();
    body.append('package', file);
    importButton.disabled = true;
    try {
      const response = await fetch(`${endpoint}/import`, {method: 'POST', credentials: 'same-origin', body});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Unable to import scoring methodologies.');
      setProfileCollection(payload);
      discardUnsavedChanges();
      render();
      setStatus(kpiStatus, 'Scoring methodologies imported into this workspace.', 'success');
      setStatus(priorityStatus, 'GAP KPI priority imported.', 'success');
      setStatus(hierarchyStatus, 'Scoring aggregation hierarchy imported.', 'success');
    } catch (error) {
      setStatus(kpiStatus, error.message || 'Unable to import scoring methodologies.', 'error');
    } finally {
      importButton.disabled = false;
      importFile.value = '';
    }
  });

  kpiForm.addEventListener('input', (event) => {
    const target = event.target;
    if (target.matches('[data-scoring-environment], [data-scoring-weight-mode]')) return;
    kpiDirty = true;
    if (target.matches('[data-environment-total-points]')) {
      const message = applyEnvironmentPointsEdit(target);
      setStatus(kpiStatus, message || 'Unsaved KPI changes. Environment points are distributed using its relative KPI weights.', target.getAttribute('aria-invalid') ? 'error' : '');
      return;
    }
    if (target.matches('[data-environment-total-weight]')) {
      const message = applyEnvironmentWeightEdit(target);
      setStatus(kpiStatus, message || 'Unsaved KPI changes. The global points total is preserved.', target.getAttribute('aria-invalid') ? 'error' : '');
      return;
    }
    if (target.matches('[data-max-points]')) updateDerivedWeights();
    if (target.matches('[data-environment-g1]')) {
      const environment = configuration?.scope?.environments?.[environmentSelect.value];
      if (environment) environment.g_level_1 = target.value;
      setStatus(kpiStatus, 'Unsaved KPI changes. Save to apply this source selector.');
      return;
    }
    if (target.matches('[data-environment-g2]')) {
      const environment = configuration?.scope?.environments?.[environmentSelect.value];
      if (environment) {
        if (target.value.trim()) environment.g_level_2 = target.value;
        else delete environment.g_level_2;
      }
      setStatus(kpiStatus, 'Unsaved KPI changes. Save to apply this source selector.');
      return;
    }
    if (target.matches('[data-kpi-formula]')) syncFormulaDependentControls(target.closest('tr[data-kpi-code]'));
    if (target.matches('[data-weight-environment-input]')) {
      const message = applyWeightEdit(target);
      if (message) {
        setStatus(kpiStatus, message, 'error');
        return;
      }
    }
    if (target.matches('[data-kpi-category]')) updateCategoryTotals();
    const row = target.closest('tr[data-kpi-code]');
    if (row) captureSelectedContext(row);
    setStatus(kpiStatus, `Unsaved KPI changes${weightMode === 'weight' ? '. Weight edits preserve the environment total and redistribute the other KPIs.' : '.'}`);
  });
  kpiForm.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('[data-scoring-environment], [data-scoring-weight-mode]')) return;
    kpiDirty = true;
    if (target.matches('[data-kpi-category]')) renderCategoryGroups();
    if (target.matches('[data-ultra-mode]')) syncUltraInput(target.closest('tr[data-kpi-code]'));
    if (target.matches('[data-weight-environment-input]')) return;
    if (target.matches('[data-environment-total-points]') || target.matches('[data-environment-total-weight]')) return;
    const row = target.closest('tr[data-kpi-code]');
    if (row) captureSelectedContext(row);
    setStatus(kpiStatus, 'Unsaved KPI changes.');
  });
  kpiForm.addEventListener('click', (event) => {
    const addBelow = event.target.closest('[data-kpi-add-below]');
    if (addBelow && kpiRows.contains(addBelow)) {
      addKpi(addBelow.closest('tr[data-kpi-code]'));
      return;
    }
    const move = event.target.closest('[data-kpi-move]');
    if (move && kpiRows.contains(move) && !move.disabled) {
      moveKpiWithinCategory(move.closest('tr[data-kpi-code]'), move.dataset.kpiMove);
      return;
    }
    const button = event.target.closest('[data-kpi-delete]');
    if (!button || !kpiRows.contains(button) || button.disabled) return;
    button.closest('tr[data-kpi-code]').remove();
    renderCategoryGroups();
    refreshKpiActionButtons();
    updateDerivedWeights();
    kpiDirty = true;
    setStatus(kpiStatus, 'Unsaved KPI changes. Save the configuration to apply this deletion.');
  });
  kpiForm.addEventListener('submit', (event) => {
    event.preventDefault();
    saveKpis();
  });

  environmentSelect.addEventListener('change', async () => {
    rowMetrics().forEach((row) => captureSelectedContext(row, lastEnvironment));
    lastEnvironment = environmentSelect.value;
    rowMetrics().forEach((row) => hydrateSelectedContext(row, lastEnvironment));
    syncEnvironmentSourceFields();
    syncWeightMode();
    updateDerivedWeights();
    setStatus(kpiStatus, kpiDirty ? 'Unsaved KPI changes are preserved while switching environments.' : '');
  });

  weightModeSelect?.addEventListener('change', () => {
    weightMode = weightModeSelect.value === 'weight' ? 'weight' : 'points';
    if (weightMode === 'points') rowMetrics().forEach((row) => row.querySelector('[data-weight-environment-input]')?.removeAttribute('aria-invalid'));
    environmentTotalPointsInput?.removeAttribute('aria-invalid');
    environmentTotalWeightInput?.removeAttribute('aria-invalid');
    updateDerivedWeights();
    syncWeightMode();
    setStatus(kpiStatus, weightMode === 'weight'
      ? 'KPI weights are relative to the selected environment. Editing a KPI weight preserves that environment total and redistributes its other KPIs proportionally. Environment weight preserves the overall points total.'
      : 'Edit maximum points directly. Changing an environment total distributes its points using the relative KPI weights.');
  });

  addKpiButton?.addEventListener('click', addKpi);
  distributePointsButton?.addEventListener('click', distributeEnvironmentPoints);
  createEnvironmentButton?.addEventListener('click', createEnvironment);
  renameEnvironmentButton?.addEventListener('click', renameEnvironment);
  deleteEnvironmentButton?.addEventListener('click', deleteEnvironment);
  profileSelect?.addEventListener('change', () => activateProfile(profileSelect.value));
  profileActions.forEach((button) => button.addEventListener('click', () => runProfileAction(button.dataset.scoringProfileAction)));

  priorityForm.addEventListener('click', (event) => {
    const button = event.target.closest('[data-priority-move]');
    if (!button || !priorityRows.contains(button)) return;
    const row = button.closest('tr[data-kpi-code]');
    const neighbor = button.dataset.priorityMove === 'up' ? row.previousElementSibling : row.nextElementSibling;
    if (!row || !neighbor) return;
    if (button.dataset.priorityMove === 'up') priorityRows.insertBefore(row, neighbor);
    else priorityRows.insertBefore(neighbor, row);
    refreshPriorityButtons();
    priorityDirty = true;
    setStatus(priorityStatus, 'Unsaved GAP KPI priority changes.');
  });
  priorityForm.addEventListener('submit', (event) => {
    event.preventDefault();
    savePriority();
  });

  hierarchyForm?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-hierarchy-move]');
    if (!button || !hierarchyRows?.contains(button)) return;
    const row = button.closest('tr[data-aggregation-level]');
    const neighbor = button.dataset.hierarchyMove === 'up' ? row.previousElementSibling : row.nextElementSibling;
    if (!row || !neighbor) return;
    if (button.dataset.hierarchyMove === 'up') hierarchyRows.insertBefore(row, neighbor);
    else hierarchyRows.insertBefore(neighbor, row);
    hierarchyOrder = Array.from(hierarchyRows.querySelectorAll('tr[data-aggregation-level]'), (item) => item.dataset.aggregationLevel);
    hierarchyDirty = true;
    refreshHierarchyButtons();
    setStatus(hierarchyStatus, 'Unsaved scoring aggregation hierarchy changes.');
  });
  hierarchyForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    saveHierarchy();
  });

  loadProfiles().then((loaded) => {
    setProfileCollection(loaded);
    render();
    if (window.location.hash) openScoringConfigHashTarget();
  }).catch((error) => {
    setStatus(kpiStatus, error.message || 'Unable to load scoring methodologies.', 'error');
    setStatus(priorityStatus, error.message || 'Unable to load GAP KPI priority.', 'error');
    setStatus(hierarchyStatus, error.message || 'Unable to load scoring aggregation hierarchy.', 'error');
    if (kpiSave) kpiSave.disabled = true;
    if (prioritySave) prioritySave.disabled = true;
    if (hierarchySave) hierarchySave.disabled = true;
    if (window.location.hash) openScoringConfigHashTarget();
  });

  const openScoringConfigHashTarget = () => {
    const targetId = decodeURIComponent(window.location.hash.slice(1));
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target || target.tagName.toLowerCase() !== 'details') return;
    let ancestor = target.parentElement;
    while (ancestor) {
      if (ancestor.tagName?.toLowerCase() === 'details') ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    target.open = true;
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      target.scrollIntoView({behavior: 'smooth', block: 'start'});
    }));
  };
  window.addEventListener('hashchange', openScoringConfigHashTarget);
  if (window.location.hash) window.requestAnimationFrame(() => window.requestAnimationFrame(openScoringConfigHashTarget));
})();
