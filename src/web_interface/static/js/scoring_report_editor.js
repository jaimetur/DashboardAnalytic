// Scoring report editor: scenarios with their filters, aggregation levels and the
// content of each scoring. Used by the Scoring & GAP Analysis exports and by the
// Scoring artifact of Reporting Jobs.
(() => {
  const LEVELS = ['Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign'];
  const FILTERS = ['Operator', 'Operator_Vendor', 'Vendor_Operator', 'Vendor', 'Region', 'Cluster', 'City', 'Campaign'];
  const SCORINGS = [['best_network', 'Best Network'], ['most_reliable', 'Most Reliable Network']];
  const CHART_OPTIONS = [
    ['service', 'Scoring per Service'], ['category', 'Scoring per Category'],
    ['breakdown', 'Scoring per Category (Breakdown)'], ['location_cards', 'Scoring per City / Cluster / Region cards'],
    ['trend', 'Scoring trend (more than four campaigns)'],
  ];
  const TABLE_OPTIONS = [
    ['summary', 'Category table'], ['breakdown', 'Breakdown table'], ['kpi_values', 'Show KPI values'],
    ['gap_values', 'Show GAP values'], ['campaign_comparison', 'Campaign comparison (two latest campaigns)'],
  ];
  const GAP_OPTIONS = [
    ['all_operators', 'Table comparing all the chosen operators'], ['individual', 'Individual tables against the reference'],
    ['profile', 'KPI GAP Profile'], ['points_loss_map', 'Points lost per City map'],
  ];
  const DEFAULT_OPERATORS = /^(vf|vodafone|3|three|h3g)(?![a-z0-9])/i;

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function defaultOptions(operators) {
    return {
      enabled: true, environments: 'all',
      charts: {service: true, category: true, breakdown: true, location_cards: true, trend: true},
      tables: {summary: true, breakdown: true, kpi_values: false, gap_values: false, campaign_comparison: true},
      gap: {operators: (operators || []).filter((name) => DEFAULT_OPERATORS.test(String(name).trim())),
        all_operators: true, individual: true, profile: true, points_loss_map: true},
    };
  }

  function defaultScenario({name = 'National', filters = {}, levels = ['Operator'], mainCities = false, operators = []} = {}) {
    return {
      name, context_filters: clone(filters), main_cities: mainCities,
      // Campaign is always included: a scenario with a single campaign leaves the level out.
      aggregation_levels: ['Operator', ...LEVELS.filter((level) => level !== 'Operator' && (levels.includes(level) || level === 'Campaign'))],
      scorings: Object.fromEntries(SCORINGS.map(([key]) => [key, defaultOptions(operators)])),
    };
  }

  function defaultConfiguration(context = {}) {
    return {scenarios: [defaultScenario(context)]};
  }

  function checkbox(label, checked, onChange, title = '') {
    const wrapper = el('label', 'scoring-report-check');
    const input = el('input');
    input.type = 'checkbox';
    input.checked = Boolean(checked);
    input.addEventListener('change', () => onChange(input.checked));
    wrapper.append(input, el('span', '', label));
    if (title) wrapper.title = title;
    return wrapper;
  }

  // A compact multi-value dropdown: an empty selection means every value.
  // Campaigns as the workspace Campaign Maps show and order them (campaign_labels.js); the filter keeps the full value.
  const campaignField = (label) => label === 'Campaign' && typeof globalThis.campaignLabel === 'function';

  document.addEventListener('pointerdown', (event) => {
    document.querySelectorAll('details.scoring-report-picker[open]').forEach((picker) => {
      if (!picker.contains(event.target)) picker.open = false;
    });
  });

  function checklist(label, values, selected, onChange, {preset = null, allOption = false} = {}) {
    const wrapper = el('details', 'scoring-report-picker');
    // One picker open at a time; it closes when opening another one or clicking outside.
    wrapper.addEventListener('toggle', () => {
      if (!wrapper.open) return;
      document.querySelectorAll('details.scoring-report-picker[open]').forEach((other) => {
        if (other !== wrapper) other.open = false;
      });
    });
    const summary = el('summary');
    const display = (value) => (campaignField(label) ? globalThis.campaignLabel(value) || value : value);
    const update = () => {
      // Chosen values in the order of the list.
      const chosen = [...known.filter((value) => selection.has(value)), ...[...selection].filter((value) => !known.includes(value))].map(display);
      summary.textContent = `${label}: ${preset?.checked ? preset.label : chosen.length ? chosen.join(', ') : 'All'}`;
      summary.title = summary.textContent;
    };
    const selection = new Set(selected || []);
    const list = el('div', 'scoring-report-picker-list');
    // Typing filters the listed values; presets such as Main Cities stay visible.
    const search = el('input', 'scoring-report-picker-search');
    search.type = 'search';
    search.placeholder = 'Filter values…';
    search.setAttribute('aria-label', `Filter ${label} values`);
    const valueRows = [];
    search.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      valueRows.forEach((row) => { row.hidden = Boolean(query) && !row.textContent.toLocaleLowerCase().includes(query); });
    });
    wrapper.addEventListener('toggle', () => {
      if (!wrapper.open) return;
      search.value = '';
      valueRows.forEach((row) => { row.hidden = false; });
      if (valueRows.length > 1) search.focus();
    });
    const known = [...new Set([...(values || []), ...(selected || [])])];
    if (campaignField(label) && typeof globalThis.campaignCompare === 'function') known.sort(globalThis.campaignCompare);
    // All: no restriction, so every value of the CDRs at generation time is included (also new ones).
    let allBox = null;
    let presetBox = null;
    const valueBoxes = new Map();
    const syncBoxes = () => {
      const all = Boolean(allBox?.checked);
      valueBoxes.forEach((box, value) => { box.checked = all || selection.has(value); box.disabled = all; });
    };
    if (preset) {
      const presetRow = checkbox(preset.label, preset.checked, (checked) => {
        preset.checked = checked;
        preset.onChange(checked);
        if (allBox && checked) { allBox.checked = false; syncBoxes(); }
        update();
      });
      presetBox = presetRow.querySelector('input');
      list.append(presetRow);
    }
    if (allOption && known.length) {
      const allRow = checkbox('All', !selection.size && !preset?.checked, (checked) => {
        selection.clear();
        if (checked) {
          if (presetBox?.checked) { presetBox.checked = false; preset.checked = false; preset.onChange(false); }
        } else {
          known.forEach((value) => selection.add(value));
        }
        onChange([...selection]);
        syncBoxes();
        update();
      }, 'Every value of the selected CDRs when the report is generated, also values that appear later');
      allRow.classList.add('scoring-report-all');
      allBox = allRow.querySelector('input');
      list.append(allRow);
    }
    if (!known.length) list.append(el('span', 'scoring-report-muted', 'No values in the selected CDRs'));
    for (const value of known) {
      const row = checkbox(display(value), selection.has(value), (checked) => {
        if (checked) selection.add(value); else selection.delete(value);
        // Clearing every value means All again.
        if (allBox) allBox.checked = !selection.size && !preset?.checked;
        onChange([...selection]);
        syncBoxes();
        update();
      });
      valueBoxes.set(value, row.querySelector('input'));
      valueRows.push(row);
      list.append(row);
    }
    syncBoxes();
    if (valueRows.length > 1) list.prepend(search);
    update();
    wrapper.append(summary, list);
    return wrapper;
  }

  function optionGroup(title, options, values, onChange) {
    const group = el('fieldset', 'scoring-report-group');
    group.append(el('legend', '', title));
    for (const [key, label] of options) group.append(checkbox(label, values[key], (checked) => onChange(key, checked)));
    return group;
  }

  function scoringPanel(scenario, key, label, operators, rerender) {
    const options = scenario.scorings[key];
    const panel = el('section', `scoring-report-scoring scoring-report-${key}`);
    const head = el('div', 'scoring-report-scoring-head');
    head.append(checkbox(`${label} scoring`, options.enabled, (checked) => { options.enabled = checked; rerender(); }));
    const environments = el('select');
    for (const [value, text] of [['all', 'All Environments only'], ['split', 'All Environments and each environment']]) {
      const option = el('option', '', text);
      option.value = value;
      environments.append(option);
    }
    environments.value = options.environments;
    environments.addEventListener('change', () => { options.environments = environments.value; });
    environments.disabled = !options.enabled;
    head.append(environments);
    panel.append(head);
    if (!options.enabled) return panel;
    const body = el('div', 'scoring-report-scoring-body');
    body.append(
      optionGroup('Scoring Charts', CHART_OPTIONS.map(([option, text]) => [option, text.startsWith('Scoring per') ? `${label} ${text}` : text]),
        options.charts, (option, checked) => { options.charts[option] = checked; }),
      optionGroup('Scoring Tables', TABLE_OPTIONS, options.tables, (option, checked) => { options.tables[option] = checked; }),
    );
    const gap = optionGroup('GAP Analysis', GAP_OPTIONS, options.gap, (option, checked) => { options.gap[option] = checked; });
    gap.prepend(checklist('Operators to compare', operators, options.gap.operators,
      (values) => { options.gap.operators = values; }));
    body.append(gap);
    panel.append(body);
    return panel;
  }

  function scenarioCard(state, index, context, rerender) {
    const scenario = state.scenarios[index];
    const card = el('article', 'scoring-report-scenario');
    const head = el('div', 'scoring-report-scenario-head');
    const name = el('input');
    name.type = 'text';
    name.maxLength = 80;
    name.value = scenario.name;
    name.setAttribute('aria-label', `Name of scenario ${index + 1}`);
    name.addEventListener('input', () => { scenario.name = name.value; });
    head.append(el('strong', 'scoring-report-index', `${index + 1}`), name);
    const actions = el('div', 'scoring-report-actions');
    const action = (text, title, disabled, handler) => {
      const button = el('button', 'ghost-link', text);
      button.type = 'button';
      button.title = title;
      button.disabled = disabled;
      button.addEventListener('click', handler);
      actions.append(button);
    };
    action('↑', 'Move up', index === 0, () => { state.scenarios.splice(index - 1, 0, ...state.scenarios.splice(index, 1)); rerender(); });
    action('↓', 'Move down', index === state.scenarios.length - 1, () => { state.scenarios.splice(index + 1, 0, ...state.scenarios.splice(index, 1)); rerender(); });
    action('Duplicate', 'Duplicate this scenario', state.scenarios.length >= 20, () => {
      const copy = clone(scenario);
      copy.name = `${scenario.name} (copy)`;
      state.scenarios.splice(index + 1, 0, copy);
      rerender();
    });
    action('Remove', 'Remove this scenario', state.scenarios.length <= 1, () => { state.scenarios.splice(index, 1); rerender(); });
    head.append(actions);
    card.append(head);

    const filters = el('div', 'scoring-report-filters');
    for (const field of FILTERS) {
      const preset = field === 'City' && (context.mainCities || []).length ? {
        label: 'Main Cities', checked: scenario.main_cities,
        onChange: (checked) => { scenario.main_cities = checked; },
      } : null;
      filters.append(checklist(field, context.filterOptions?.[field] || [], scenario.context_filters[field] || [], (values) => {
        if (values.length) scenario.context_filters[field] = values; else delete scenario.context_filters[field];
      }, {preset, allOption: true}));
    }
    const levels = el('div', 'scoring-report-levels');
    levels.append(el('span', 'scoring-report-label', 'Aggregation levels:'));
    for (const level of LEVELS) {
      const box = checkbox(level, scenario.aggregation_levels.includes(level), (checked) => {
        scenario.aggregation_levels = LEVELS.filter((item) => item === 'Operator'
          || (item === level ? checked : scenario.aggregation_levels.includes(item)));
      });
      if (level === 'Operator') { box.querySelector('input').disabled = true; box.title = 'Operator is required'; }
      levels.append(box);
    }
    const scorings = el('div', 'scoring-report-scorings');
    for (const [key, label] of SCORINGS) scorings.append(scoringPanel(scenario, key, label, context.operators || [], rerender));
    card.append(filters, levels, scorings);
    return card;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The request failed.');
    return payload;
  }

  // A small dialog over the editor (the browser prompt and confirm look out of place).
  // With `value` it asks for a name and resolves with it, otherwise with true; null when cancelled.
  function ask(host, {title, copy = '', value = null, confirmLabel = 'Save', danger = false}) {
    return new Promise((resolve) => {
      const dialog = el('dialog', 'scoring-report-ask');
      const form = el('form');
      form.method = 'dialog';
      form.append(el('h3', '', title));
      if (copy) form.append(el('p', 'scoring-report-ask-copy', copy));
      let input = null;
      if (value !== null) {
        input = el('input');
        input.type = 'text';
        input.maxLength = 80;
        input.required = true;
        input.value = value;
        input.setAttribute('aria-label', title);
        form.append(input);
      }
      const actions = el('div', 'scoring-report-ask-actions');
      const cancel = el('button', '', 'Cancel');
      cancel.type = 'button';
      const accept = el('button', danger ? 'danger-button' : 'primary-button', confirmLabel);
      accept.type = 'submit';
      actions.append(cancel, accept);
      form.append(actions);
      dialog.append(form);
      let result = null;
      cancel.addEventListener('click', () => dialog.close());
      form.addEventListener('submit', (event) => {
        if (input && !input.value.trim()) { event.preventDefault(); input.focus(); return; }
        result = input ? input.value.trim() : true;
      });
      dialog.addEventListener('close', () => { dialog.remove(); resolve(result); });
      host.append(dialog);
      dialog.showModal();
      if (input) { input.focus(); input.select(); } else accept.focus();
    });
  }

  // PowerPoint and Word actions use the colours and icons of the export buttons of every module.
  const DOCUMENT_ACTIONS = {
    ppt: ['document-export-powerpoint', '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 13l3-3 2 2 4-4"/>'],
    word: ['document-export-word', '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M8.5 12l1.2 5 1.8-4 1.8 4 1.2-5"/>'],
  };

  function actionButton(action, text) {
    const documentAction = DOCUMENT_ACTIONS[action === 'powerpoint' ? 'ppt' : action];
    if (!documentAction) return el('button', 'primary-button', text);
    const node = el('button', `document-export-action ${documentAction[0]}`);
    node.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${documentAction[1]}</svg>`;
    node.append(text);
    return node;
  }

  // Operators are shown and saved with their Operator Maps label: source spellings (for example
  // VF_UK) become their canonical Operator, in the order of the Operator Maps.
  function operatorCanonicalizer(groups = []) {
    const canonical = new Map();
    groups.forEach((group) => {
      const name = String(group.canonical || '').trim();
      if (!name) return;
      [name, ...(group.aliases || [])].forEach((alias) => canonical.set(String(alias).trim().toLocaleLowerCase(), name));
    });
    const order = groups.map((group) => String(group.canonical || '').trim());
    const one = (value) => canonical.get(String(value ?? '').trim().toLocaleLowerCase()) || String(value ?? '').trim();
    const list = (values) => [...new Set((values || []).map(one).filter(Boolean))];
    const sorted = (values) => list(values).sort((left, right) => {
      const a = order.indexOf(left);
      const b = order.indexOf(right);
      return (a < 0 ? order.length : a) - (b < 0 ? order.length : b) || left.localeCompare(right);
    });
    // Saved Operators that the CDRs no longer have (for example a renamed Operator) are left out.
    const available = (values, known) => {
      const names = list(values);
      return known.length ? names.filter((name) => known.includes(name)) : names;
    };
    const configuration = (config, {filterOperators = [], gapOperators = []} = {}) => {
      (config?.scenarios || []).forEach((scenario) => {
        if (scenario.context_filters?.Operator) {
          scenario.context_filters.Operator = available(scenario.context_filters.Operator, filterOperators);
          if (!scenario.context_filters.Operator.length) delete scenario.context_filters.Operator;
        }
        Object.values(scenario.scorings || {}).forEach((options) => {
          if (options?.gap?.operators) options.gap.operators = available(options.gap.operators, gapOperators);
        });
      });
      return config;
    };
    return {list, sorted, configuration};
  }

  // Opens the editor. Resolves with {configuration, action} or null when cancelled.
  function open({configuration, context: rawContext = {}, actions = [['apply', 'Apply']], title = 'Scoring report'} = {}) {
    return new Promise((resolve) => {
      const operators = operatorCanonicalizer(rawContext.operatorGroups || []);
      const context = {
        ...rawContext,
        operators: operators.sorted(rawContext.operators || []),
        defaults: rawContext.defaults && {...rawContext.defaults, operators: operators.sorted(rawContext.defaults.operators || [])},
        filterOptions: {...(rawContext.filterOptions || {}),
          ...(rawContext.filterOptions?.Operator ? {Operator: operators.sorted(rawContext.filterOptions.Operator)} : {})},
      };
      const knownOperators = {filterOperators: context.filterOptions.Operator || [], gapOperators: context.operators};
      const state = operators.configuration(clone(configuration || defaultConfiguration(context.defaults)), knownOperators);
      const dialog = el('dialog', 'scoring-report-dialog');
      const header = el('div', 'scoring-report-header');
      header.append(el('h2', '', title));
      const toolbar = el('div', 'scoring-report-toolbar');
      const saved = el('select');
      saved.setAttribute('aria-label', 'Saved report configurations');
      const status = el('p', 'scoring-report-status');
      const setStatus = (text, tone = '') => { status.textContent = text; status.dataset.tone = tone; };
      let savedConfigurations = [];
      // The Default configuration is always listed after the placeholder and before the saved ones.
      const DEFAULT_NAME = 'Default';
      const DEFAULT_VALUE = '__default__';
      const refreshSaved = (payload) => {
        savedConfigurations = payload?.configurations || [];
        saved.replaceChildren(el('option', '', savedConfigurations.length ? 'Saved configurations…' : 'No saved configurations'));
        saved.firstChild.value = '';
        const defaultOption = el('option', '', DEFAULT_NAME);
        defaultOption.value = DEFAULT_VALUE;
        saved.append(defaultOption);
        for (const item of savedConfigurations) {
          const option = el('option', '', item.name);
          option.value = item.name;
          saved.append(option);
        }
      };
      const button = (text, handler, className = 'ghost-link', titleText = '') => {
        const node = el('button', className, text);
        node.type = 'button';
        if (titleText) node.title = titleText;
        node.addEventListener('click', handler);
        toolbar.append(node);
        return node;
      };
      toolbar.append(saved);
      const useDefault = () => {
        state.scenarios = defaultConfiguration(context.defaults).scenarios;
        render();
        saved.value = DEFAULT_VALUE;
        setStatus('Default configuration: one scenario with the calculation filters and aggregation.', 'success');
      };
      button('Load', () => {
        if (saved.value === DEFAULT_VALUE) { useDefault(); return; }
        const item = savedConfigurations.find((entry) => entry.name === saved.value);
        if (!item) { setStatus('Choose a saved configuration to load.', 'error'); return; }
        state.scenarios = operators.configuration(clone(item.configuration), knownOperators).scenarios;
        render();
        setStatus(`Loaded “${item.name}”.`, 'success');
      }, 'ghost-link', 'Replace the scenarios with the chosen saved configuration');
      button('Save as…', async () => {
        const current = (saved.value !== DEFAULT_VALUE && saved.value) || state.scenarios[0]?.name || '';
        const name = await ask(dialog, {
          title: 'Save report configuration', value: current,
          copy: 'Name of the configuration in this workspace. Saving with the name of a saved configuration replaces it.',
        });
        if (!name) return;
        if (name.toLocaleLowerCase() === DEFAULT_NAME.toLocaleLowerCase()) {
          setStatus('“Default” is the name of the default configuration: choose another name.', 'error');
          return;
        }
        try {
          refreshSaved(await api('/api/scoring/report-configurations', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name.trim(), configuration: state}),
          }));
          saved.value = name.trim();
          setStatus(`Saved “${name.trim()}”.`, 'success');
        } catch (error) { setStatus(error.message, 'error'); }
      }, 'ghost-link', 'Save these scenarios with a name in the workspace');
      button('Delete', async () => {
        if (!saved.value) { setStatus('Choose a saved configuration to delete.', 'error'); return; }
        if (saved.value === DEFAULT_VALUE) { setStatus('The Default configuration cannot be deleted.', 'error'); return; }
        if (!await ask(dialog, {title: 'Delete report configuration', copy: `Delete the saved report configuration “${saved.value}”?`,
          confirmLabel: 'Delete', danger: true})) return;
        try {
          refreshSaved(await api(`/api/scoring/report-configurations?name=${encodeURIComponent(saved.value)}`, {method: 'DELETE'}));
          setStatus('Configuration deleted.', 'success');
        } catch (error) { setStatus(error.message, 'error'); }
      });
      button('Default', useDefault, 'ghost-link', 'Go back to the default report configuration');
      button('Export JSON', () => { window.location.href = '/api/scoring/report-configurations/export'; }, 'ghost-link',
        'Download every saved report configuration');
      const importInput = el('input');
      importInput.type = 'file';
      importInput.accept = 'application/json,.json';
      importInput.hidden = true;
      importInput.addEventListener('change', async () => {
        const file = importInput.files?.[0];
        if (!file) return;
        const form = new FormData();
        form.append('package', file);
        try {
          refreshSaved(await api('/api/scoring/report-configurations/import', {method: 'POST', body: form}));
          setStatus('Report configurations imported.', 'success');
        } catch (error) { setStatus(error.message, 'error'); }
        importInput.value = '';
      });
      toolbar.append(importInput);
      button('Import JSON', () => importInput.click(), 'ghost-link', 'Add report configurations from a JSON file');
      header.append(toolbar);

      const list = el('div', 'scoring-report-scenarios');
      const add = el('button', 'ghost-link scoring-report-add', '+ Add scenario');
      add.type = 'button';
      add.addEventListener('click', () => {
        if (state.scenarios.length >= 20) return;
        state.scenarios.push(defaultScenario({...context.defaults, name: `Scenario ${state.scenarios.length + 1}`}));
        render();
        list.lastElementChild?.scrollIntoView({block: 'nearest'});
      });
      const footer = el('div', 'scoring-report-footer');
      const close = (result) => { dialog.close(); dialog.remove(); resolve(result); };
      const cancel = el('button', 'ghost-link', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', () => close(null));
      footer.append(status, cancel);
      for (const [action, text] of actions) {
        const node = actionButton(action, text);
        node.type = 'button';
        node.addEventListener('click', () => {
          if (!state.scenarios.some((scenario) => SCORINGS.some(([key]) => scenario.scorings[key].enabled))) {
            setStatus('Include the Best Network or the Most Reliable Network scoring in at least one scenario.', 'error');
            return;
          }
          state.scenarios.forEach((scenario, index) => { scenario.name = scenario.name.trim() || `Scenario ${index + 1}`; });
          close({configuration: clone(state), action});
        });
        footer.append(node);
      }
      function render() {
        list.replaceChildren(...state.scenarios.map((_scenario, index) => scenarioCard(state, index, context, render)));
        add.disabled = state.scenarios.length >= 20;
      }
      render();
      dialog.append(header, list, add, footer);
      dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(null); });
      document.body.append(dialog);
      dialog.showModal();
      refreshSaved(null);
      api('/api/scoring/report-configurations').then(refreshSaved).catch(() => {});
    });
  }

  window.ScoringReportEditor = {open, defaultConfiguration, defaultScenario, defaultOptions};
})();
