/* Reporting: scheduled Reporting Jobs, their editor and run history. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const FORMAT_LABELS = {powerpoint: 'PowerPoint', word: 'Word'};
  const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const SCORING_FILTERS = [['Operator', 'Operator'], ['Vendor', 'Vendor'], ['Region', 'Region'], ['City', 'City'], ['Campaign', 'Campaign']];
  const NETWORK_FILTERS = [['operators', 'Operator'], ['vendors', 'Vendor'], ['campaigns', 'Campaign'], ['regions', 'Region'], ['cities', 'City']];
  const STATUS_LABELS = {queued: 'Queued', running: 'Running', sent: 'Sent', completed: 'Completed', partial: 'Partial', failed: 'Failed'};

  let state = {tasks: [], runs: [], can_edit: false};
  let options = null;
  let editingId = null;
  let pollTimer = null;

  const status = (message, tone = '') => {
    const element = $('rj-status');
    element.textContent = message || '';
    element.dataset.tone = tone;
  };
  const api = async (url, init = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...init,
      headers: init.body ? {'Content-Type': 'application/json', ...(init.headers || {})} : init.headers});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The request failed.');
    return payload;
  };
  const cellWith = (...children) => { const cell = node('td'); cell.append(...children); return cell; };
  const emptyRow = (body, text, columns) => {
    const cell = node('td', text, 'form-note'); cell.colSpan = columns;
    const row = node('tr'); row.append(cell); body.replaceChildren(row);
  };
  const localTime = (value) => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
  };

  // -- reusable pickers ---------------------------------------------------
  // A filterable multi-select dropdown; getValue() returns the checked values.
  function multiPicker(label, values, selected = [], {allLabel = ''} = {}) {
    const wrapper = node('details', undefined, 'workspace-user-picker rj-multi');
    const summary = node('summary');
    const caption = node('span');
    summary.append(caption, node('span', '', 'workspace-user-picker-chevron'));
    const menu = node('div', undefined, 'workspace-user-picker-menu');
    const search = node('input', undefined, 'workspace-user-picker-search');
    search.type = 'search'; search.placeholder = 'Filter…'; search.setAttribute('aria-label', `Filter ${label}`);
    menu.append(search);
    const chosen = new Set(selected.map(String));
    const boxes = values.map((value) => {
      const row = node('label');
      const box = node('input'); box.type = 'checkbox'; box.value = String(value); box.checked = chosen.has(String(value));
      row.append(box, node('span', String(value)));
      menu.append(row);
      return box;
    });
    if (!values.length) menu.append(node('p', 'No values available.', 'table-help'));
    const refresh = () => {
      const count = boxes.filter((box) => box.checked).length;
      caption.textContent = `${label}: ${count ? `${count} selected` : (allLabel || 'All')}`;
    };
    menu.addEventListener('change', refresh);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      boxes.forEach((box) => { box.parentElement.hidden = Boolean(query) && !box.value.toLocaleLowerCase().includes(query); });
    });
    wrapper.append(summary, menu);
    refresh();
    wrapper.getValue = () => boxes.filter((box) => box.checked).map((box) => box.value);
    return wrapper;
  }

  // Dataset checklist with an "every ready dataset" switch (an empty selection).
  function datasetPicker(container, datasets, selected, allText) {
    container.replaceChildren();
    const all = node('label', undefined, 'rj-check');
    const allBox = node('input'); allBox.type = 'checkbox'; allBox.checked = !selected.length;
    all.append(allBox, node('span', allText));
    const list = node('div', undefined, 'rj-dataset-list');
    const chosen = new Set(selected.map(Number));
    const boxes = datasets.map((dataset) => {
      const row = node('label', undefined, 'rj-check');
      const box = node('input'); box.type = 'checkbox'; box.value = dataset.id; box.checked = chosen.has(dataset.id);
      row.append(box, node('span', `${dataset.file_name} (${dataset.kind}${dataset.nr_mode ? ` · ${dataset.nr_mode}` : ''})`));
      list.append(row);
      return box;
    });
    const sync = () => { list.classList.toggle('is-disabled', allBox.checked); boxes.forEach((box) => { box.disabled = allBox.checked; }); };
    allBox.addEventListener('change', sync);
    sync();
    container.append(all, list);
    container.getValue = () => (allBox.checked ? [] : boxes.filter((box) => box.checked).map((box) => Number(box.value)));
  }

  function formatChoices(container, prefix, selected) {
    container.replaceChildren();
    options.formats.forEach((format) => {
      const row = node('label', undefined, 'rj-check');
      const box = node('input'); box.type = 'checkbox'; box.value = format; box.checked = selected.includes(format);
      box.dataset.format = prefix;
      row.append(box, node('span', FORMAT_LABELS[format] || format));
      container.append(row);
    });
    container.getValue = () => [...container.querySelectorAll('input:checked')].map((box) => box.value);
  }

  const select = (choices, value) => {
    const element = node('select');
    choices.forEach(([choice, label]) => {
      const option = node('option', label); option.value = choice; option.selected = String(choice) === String(value ?? '');
      element.append(option);
    });
    return element;
  };
  const field = (label, control, className = '') => {
    const wrapper = node('label', undefined, className);
    wrapper.append(document.createTextNode(label), control);
    return wrapper;
  };

  // -- artifact entries ---------------------------------------------------
  // CDR checklists grouped by type; getValue() returns {kind: [ids]}.
  function datasetsByKind(container, datasets, selected) {
    container.replaceChildren();
    const chosen = new Set(Object.values(selected || {}).flat().map(Number));
    const boxes = [];
    ['data', 'voice', 'speech'].forEach((kind) => {
      const items = datasets.filter((item) => item.kind === kind);
      if (!items.length) return;
      const group = node('div', undefined, 'rj-kind-group');
      group.append(node('strong', `CDR ${kind[0].toUpperCase()}${kind.slice(1)}`));
      items.forEach((dataset) => {
        const row = node('label', undefined, 'rj-check');
        const box = node('input'); box.type = 'checkbox'; box.value = dataset.id; box.dataset.kind = kind; box.checked = chosen.has(dataset.id);
        row.append(box, node('span', dataset.file_name));
        group.append(row); boxes.push(box);
      });
      container.append(group);
    });
    if (!boxes.length) container.append(node('p', 'No ready CDRs for this NR Mode.', 'form-note'));
    container.getValue = () => {
      const value = {};
      boxes.filter((box) => box.checked).forEach((box) => { (value[box.dataset.kind] ||= []).push(Number(box.value)); });
      return value;
    };
  }

  // A Dashboard artifact offers the Dashboard's own options: Scope, CDRs,
  // dates and every Adaptative Filter, prefilled with its saved definition.
  function dashboardEntry(entry = null) {
    const card = node('div', undefined, 'rj-entry');
    const dashboards = options.dashboards;
    // A new entry starts with the first Dashboard not added yet.
    const added = new Set([...$('rj-dashboards').children].map((card) => card.getValue?.().dashboard_id));
    const firstFree = dashboards.find((item) => !added.has(item.id)) || dashboards[0];
    const dashboard = select(dashboards.map((item) => [item.id, item.name]), entry?.dashboard_id || firstFree?.id);
    const label = node('input'); label.type = 'text'; label.placeholder = 'Optional artifact name'; label.value = entry?.label || '';
    const remove = node('button', '×', 'danger-button icon-action'); remove.type = 'button'; remove.title = 'Remove this Dashboard';
    remove.addEventListener('click', () => card.remove());
    const scope = select([['single', 'Operator Comparison'], ['multivendor', 'Multivendor Comparison']], 'single');
    const comparison = select([['vendor_only', 'Vendor Only (All Operators Combined)'], ['operator_vendor', 'Operator - Vendor']], 'operator_vendor');
    const comparisonField = field('Vendor comparison', comparison);
    const dateFrom = node('input'); dateFrom.type = 'date';
    const dateTo = node('input'); dateTo.type = 'date';
    const head = node('div', undefined, 'rj-grid');
    head.append(field('Dashboard', dashboard), field('Name in the email', label), field('Scope', scope), comparisonField,
      field('Date from (empty: oldest)', dateFrom), field('Date to (empty: newest)', dateTo), remove);
    const datasets = node('div', undefined, 'rj-picker rj-kinds');
    const filters = node('div', undefined, 'rj-filters');
    const filterNote = node('p', '', 'form-note');
    let pickers = [];
    let current = null;
    let loadTimer = null;
    let loadRequest = 0;

    const definitionFor = () => ({
      ...current.saved, scope: scope.value, vendor_comparison: comparison.value,
      datasets: datasets.getValue(), filters: {},
      date_from: dateFrom.value || 'Oldest', date_to: dateTo.value || 'Newest',
    });
    const renderFilters = (values, selected) => {
      pickers = current.fields.map((name) => [name, multiPicker(name === 'Vendor_Only' ? 'Vendor' : name, values[name] || [], selected[name] || [])]);
      filters.replaceChildren(...pickers.map(([, picker]) => picker));
    };
    // Filter values are the ones the selected CDRs offer, as in the Dashboard.
    const loadFilterValues = async () => {
      const request = ++loadRequest;
      const selected = Object.fromEntries(pickers.map(([name, picker]) => [name, picker.getValue()]));
      filterNote.textContent = 'Loading filter values of the selected CDRs…';
      try {
        const result = await api('/api/e2e-dashboards/filter-options/batch', {
          method: 'POST', body: JSON.stringify({definition: definitionFor(), fields: current.fields}),
        });
        if (request !== loadRequest) return;
        renderFilters(result.options || {}, selected);
        filterNote.textContent = 'Empty filters include every value.';
      } catch (error) {
        if (request === loadRequest) filterNote.textContent = `Filter values are unavailable: ${error.message}`;
      }
    };
    const scheduleLoad = () => { clearTimeout(loadTimer); loadTimer = setTimeout(() => { void loadFilterValues(); }, 300); };
    const apply = (config, saved) => {
      current = {saved, fields: [...new Set([...options.dashboard_filter_fields, ...(saved.custom_fields || [])])]};
      scope.value = config.scope || saved.scope || 'single';
      comparison.value = config.vendor_comparison || saved.vendor_comparison || 'operator_vendor';
      dateFrom.value = /^\d{4}-\d{2}-\d{2}$/.test(config.date_from || '') ? config.date_from : '';
      dateTo.value = /^\d{4}-\d{2}-\d{2}$/.test(config.date_to || '') ? config.date_to : '';
      const technology = String(saved.technology || 'nsa').toUpperCase();
      datasetsByKind(datasets, options.datasets.filter((item) => item.nr_mode === technology), config.datasets && Object.keys(config.datasets).length ? config.datasets : saved.datasets);
      renderFilters({}, config.filters || {});
      comparisonField.hidden = scope.value !== 'multivendor';
      scheduleLoad();
    };
    const savedDashboard = () => dashboards.find((item) => item.id === dashboard.value) || {};
    dashboard.addEventListener('change', () => { const saved = savedDashboard(); apply(saved, saved); });
    scope.addEventListener('change', () => { comparisonField.hidden = scope.value !== 'multivendor'; scheduleLoad(); });
    comparison.addEventListener('change', scheduleLoad);
    datasets.addEventListener('change', scheduleLoad);
    card.append(head, node('strong', 'CDRs'), datasets, node('strong', 'Adaptative Filters'), filterNote, filters);
    apply(entry || savedDashboard(), savedDashboard());
    card.getValue = () => ({
      dashboard_id: dashboard.value, label: label.value.trim(), scope: scope.value, vendor_comparison: comparison.value,
      datasets: datasets.getValue(), date_from: dateFrom.value, date_to: dateTo.value,
      filters: Object.fromEntries(pickers.map(([name, picker]) => [name, picker.getValue()]).filter(([, values]) => values.length)),
    });
    return card;
  }

  // A Scoring artifact offers the Scoring calculation options: NR Mode, CDRs,
  // filters, Main Cities, aggregation levels, methodology and GAP reference.
  function scoringEntry(entry = {}) {
    const card = node('div', undefined, 'rj-entry');
    const label = node('input'); label.type = 'text'; label.placeholder = 'Optional artifact name'; label.value = entry.label || '';
    const nrMode = select([['NSA', 'NSA'], ['SA', 'SA']], entry.nr_mode || 'NSA');
    const methodology = select([['', 'Default methodology'], ...options.methodologies.map((item) => [item.id, item.name])], entry.scoring_profile_id || '');
    const baseline = node('input'); baseline.type = 'text'; baseline.value = entry.baseline_operator || 'EE';
    const remove = node('button', '×', 'danger-button icon-action'); remove.type = 'button'; remove.title = 'Remove this Scoring artifact';
    remove.addEventListener('click', () => card.remove());
    const head = node('div', undefined, 'rj-grid');
    head.append(field('NR Mode', nrMode), field('Name in the email', label), field('Methodology', methodology), field('GAP reference operator', baseline), remove);
    const levels = node('div', undefined, 'rj-inline');
    levels.append(node('span', 'Aggregation levels:', 'rj-inline-label'));
    const levelBoxes = options.scoring_levels.map((level) => {
      const row = node('label', undefined, 'rj-check');
      const box = node('input'); box.type = 'checkbox'; box.value = level;
      box.checked = level === 'Operator' || (entry.aggregation_levels || []).includes(level); box.disabled = level === 'Operator';
      row.append(box, node('span', level));
      levels.append(row);
      return box;
    });
    const mainCities = node('label', undefined, 'rj-check');
    const mainBox = node('input'); mainBox.type = 'checkbox'; mainBox.checked = Boolean(entry.main_cities);
    mainCities.append(mainBox, node('span', `Main Cities only (${options.main_cities.length ? options.main_cities.join(', ') : 'none set'})`));
    const pickers = SCORING_FILTERS.map(([key, text]) => [key, multiPicker(text, options.values[text] || [], entry.context_filters?.[key] || [])]);
    const cityPicker = pickers.find(([key]) => key === 'City')[1];
    const syncCities = () => { cityPicker.hidden = mainBox.checked; };
    mainBox.addEventListener('change', syncCities); syncCities();
    const filters = node('div', undefined, 'rj-filters');
    filters.append(...pickers.map(([, picker]) => picker), mainCities);
    const datasets = node('div', undefined, 'rj-picker');
    const renderDatasets = () => datasetPicker(datasets, options.datasets.filter((item) => item.nr_mode === nrMode.value),
      entry.dataset_ids || [], 'Newest complete set of Data, Voice and Speech CDRs at each run');
    nrMode.addEventListener('change', renderDatasets); renderDatasets();
    card.append(head, levels, node('strong', 'Filters'), filters, node('strong', 'CDRs'), datasets);
    card.getValue = () => ({
      label: label.value.trim(), nr_mode: nrMode.value, dataset_ids: datasets.getValue(),
      scoring_profile_id: methodology.value, baseline_operator: baseline.value.trim() || 'EE',
      aggregation_levels: levelBoxes.filter((box) => box.checked).map((box) => box.value),
      main_cities: mainBox.checked,
      context_filters: Object.fromEntries(pickers.map(([key, picker]) => [key, picker.getValue()])
        .filter(([key, values]) => values.length && !(key === 'City' && mainBox.checked))),
    });
    return card;
  }

  // -- editor -------------------------------------------------------------
  let networkGroup = null;
  let networkFilters = [];

  function fillEditor(task) {
    const definition = task?.definition || {};
    const dataset = definition.dataset_analysis || {};
    const network = definition.network_insights || {};
    const selection = network.selection || {};
    editingId = task?.id ?? null;
    $('rj-editor-title').textContent = task?.id ? `Edit ${task.name}` : 'New Reporting Job';
    $('rj-name').value = task?.name || '';
    $('rj-da-enabled').checked = Boolean(dataset.enabled);
    formatChoices(document.querySelector('[data-rj-formats="rj-da"]'), 'rj-da', dataset.formats || ['powerpoint']);
    datasetPicker($('rj-da-datasets'), options.datasets, dataset.dataset_ids || [], 'Every ready CDR dataset at each run');
    $('rj-ni-enabled').checked = Boolean(network.enabled);
    formatChoices(document.querySelector('[data-rj-formats="rj-ni"]'), 'rj-ni', network.formats || ['powerpoint']);
    $('rj-ni-technology').replaceChildren(...Object.entries(options.technologies).map(([value, label]) => {
      const option = node('option', label); option.value = value; option.selected = value === (selection.technology || 'lte'); return option;
    }));
    $('rj-ni-coverage').value = selection.coverage_threshold ?? -110;
    $('rj-ni-interference').value = selection.interference_threshold ?? 0;
    $('rj-ni-nr-coverage').value = selection.nr_coverage_threshold ?? -115;
    $('rj-ni-nr-interference').value = selection.nr_interference_threshold ?? -3;
    // Only the thresholds of the selected technologies are shown.
    const syncRadioThresholds = () => {
      const technology = $('rj-ni-technology').value;
      document.querySelectorAll('[data-rj-ni-radio]').forEach((label) => {
        label.hidden = ![label.dataset.rjNiRadio, 'lte_nr'].includes(technology);
      });
    };
    $('rj-ni-technology').onchange = syncRadioThresholds;
    syncRadioThresholds();
    const groups = selection.group || ['operator', 'campaign'];
    $('rj-ni-group').replaceChildren(node('span', 'Grouping:', 'rj-inline-label'), ...Object.entries(options.network_groupings).map(([value, label]) => {
      const row = node('label', undefined, 'rj-check');
      const box = node('input'); box.type = 'checkbox'; box.value = value; box.checked = groups.includes(value);
      row.append(box, node('span', label));
      return row;
    }));
    networkFilters = NETWORK_FILTERS.map(([key, text]) => [key, multiPicker(text, options.values[text] || [], selection[key] || [])]);
    $('rj-ni-filters').replaceChildren(...networkFilters.map(([, picker]) => picker));
    const networkDatasets = Object.values(selection.datasets || {}).flat();
    $('rj-ni-nr-mode').value = selection.nr_mode || 'NSA';
    const renderNetworkDatasets = (selected) => datasetPicker($('rj-ni-datasets'), options.datasets.filter((item) => item.nr_mode === $('rj-ni-nr-mode').value),
      selected, 'Every ready Data, Voice and Speech CDR of this NR Mode at each run');
    $('rj-ni-nr-mode').onchange = () => renderNetworkDatasets([]);
    renderNetworkDatasets(networkDatasets);
    $('rj-dashboards').replaceChildren(...(definition.dashboards || []).map(dashboardEntry));
    $('rj-scoring').replaceChildren(...(definition.scoring || []).map(scoringEntry));
    // Only the modules the user can use offer artifacts.
    const labels = {dataset_analysis: 'Datasets Analysis', network_insights: 'Network Insights', dashboards: 'E2E Dashboards', scoring: 'Scoring & GAP Analysis'};
    const unavailable = Object.entries(options.allowed_modules).filter(([, allowed]) => !allowed).map(([module]) => module);
    document.querySelectorAll('[data-rj-module]').forEach((section) => { section.hidden = unavailable.includes(section.dataset.rjModule); });
    $('rj-modules-note').hidden = !unavailable.length;
    $('rj-modules-note').textContent = `Artifacts of modules not activated for your account are not available: ${unavailable.map((module) => labels[module]).join(', ')}.`;
    const modules = definition.modules || {};
    $('rj-providers').replaceChildren(...options.providers.map((provider) => {
      const config = modules[provider.key] || {};
      const card = node('section', undefined, 'rj-card');
      const toggle = node('label', undefined, 'rj-card-toggle');
      const box = node('input'); box.type = 'checkbox'; box.checked = Boolean(config.enabled);
      toggle.append(box, node('strong', provider.label));
      const formats = node('div', undefined, 'rj-formats');
      provider.formats.forEach((format) => {
        const row = node('label', undefined, 'rj-check');
        const choice = node('input'); choice.type = 'checkbox'; choice.value = format; choice.checked = (config.formats || [provider.formats[0]]).includes(format);
        row.append(choice, node('span', FORMAT_LABELS[format] || format));
        formats.append(row);
      });
      card.append(toggle, formats);
      card.getValue = () => [provider.key, {enabled: box.checked, formats: [...formats.querySelectorAll('input:checked')].map((item) => item.value)}];
      return card;
    }));
    $('rj-send-email').checked = Boolean(task?.send_email);
    $('rj-recipients').value = (task?.recipients || []).join(', ');
    const schedule = task?.schedule || {mode: 'manual', time: '08:00'};
    $('rj-schedule-mode').value = schedule.mode || 'manual';
    $('rj-schedule-date').value = schedule.date || '';
    $('rj-schedule-time').value = schedule.time || '08:00';
    $('rj-schedule-day').value = schedule.day_of_month || 1;
    $('rj-schedule-weekdays').replaceChildren(...WEEKDAYS.map((day, index) => {
      const row = node('label', undefined, 'rj-check');
      const box = node('input'); box.type = 'checkbox'; box.value = index; box.checked = (schedule.weekdays || [0]).includes(index);
      row.append(box, node('span', day.slice(0, 3)));
      return row;
    }));
    $('rj-enabled').checked = task ? Boolean(task.enabled) : true;
    $('rj-timezone').textContent = `Times use the application timezone ${options.timezone}. A job only runs while its workspace is the active workspace; a run that falls due meanwhile starts when the workspace is opened again.`;
    $('rj-email-note').textContent = options.email_configured
      ? 'Without email, each run only keeps its artifacts for download.'
      : 'Email delivery is not configured yet: set the SMTP server in Config → Application Config → Email Delivery.';
    syncEditor();
    $('rj-editor').hidden = false;
    $('rj-editor').open = true;
    $('rj-editor').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function syncEditor() {
    document.querySelectorAll('[data-rj-section]').forEach((section) => {
      const enabled = section.querySelector('.rj-card-toggle input').checked;
      section.querySelector('[data-rj-body]').hidden = !enabled;
    });
    document.querySelector('[data-rj-email-body]').hidden = !$('rj-send-email').checked;
    const mode = $('rj-schedule-mode').value;
    document.querySelectorAll('[data-rj-schedule]').forEach((element) => {
      element.hidden = !element.dataset.rjSchedule.split(' ').includes(mode);
    });
  }

  function editorPayload() {
    const networkIds = new Set($('rj-ni-datasets').getValue());
    const networkDatasets = {};
    options.datasets.filter((item) => networkIds.has(item.id)).forEach((item) => { (networkDatasets[item.kind] ||= []).push(item.id); });
    return {
      name: $('rj-name').value.trim(),
      definition: {
        dataset_analysis: {
          enabled: $('rj-da-enabled').checked && options.allowed_modules.dataset_analysis, formats: document.querySelector('[data-rj-formats="rj-da"]').getValue(),
          dataset_ids: $('rj-da-datasets').getValue(),
        },
        network_insights: {
          enabled: $('rj-ni-enabled').checked && options.allowed_modules.network_insights, formats: document.querySelector('[data-rj-formats="rj-ni"]').getValue(),
          selection: {
            datasets: networkDatasets, nr_mode: $('rj-ni-nr-mode').value, technology: $('rj-ni-technology').value,
            group: [...$('rj-ni-group').querySelectorAll('input:checked')].map((box) => box.value),
            coverage_threshold: Number($('rj-ni-coverage').value), interference_threshold: Number($('rj-ni-interference').value),
            nr_coverage_threshold: Number($('rj-ni-nr-coverage').value), nr_interference_threshold: Number($('rj-ni-nr-interference').value),
            ...Object.fromEntries(networkFilters.map(([key, picker]) => [key, picker.getValue()])),
          },
        },
        dashboards: [...$('rj-dashboards').children].map((card) => card.getValue()),
        scoring: [...$('rj-scoring').children].map((card) => card.getValue()),
        modules: Object.fromEntries([...$('rj-providers').children].map((card) => card.getValue())),
      },
      send_email: $('rj-send-email').checked,
      recipients: $('rj-recipients').value,
      schedule: {
        mode: $('rj-schedule-mode').value, date: $('rj-schedule-date').value, time: $('rj-schedule-time').value || '08:00',
        day_of_month: Number($('rj-schedule-day').value || 1),
        weekdays: [...$('rj-schedule-weekdays').querySelectorAll('input:checked')].map((box) => Number(box.value)),
      },
      enabled: $('rj-enabled').checked,
    };
  }

  async function ensureOptions() {
    options = await api('/api/reporting/options');
    return options;
  }

  // -- tables -------------------------------------------------------------
  const actionButton = (label, title, handler, className = 'icon-action') => {
    const button = node('button', label, className);
    button.type = 'button'; button.title = title; button.setAttribute('aria-label', title);
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await handler(); } catch (error) { status(error.message, 'error'); } finally { button.disabled = false; }
    });
    return button;
  };
  const statusBadge = (run) => {
    if (!run) return node('span', 'Never run', 'form-note');
    const badge = node('span', STATUS_LABELS[run.status] || run.status, `rj-status rj-status-${run.status}`);
    badge.title = run.error || run.message || '';
    return badge;
  };
  const downloadLink = (run) => {
    const link = node('a', '⬇', 'icon-action rj-download');
    link.href = `/api/reporting/runs/${run.id}/download`;
    link.title = 'Download the artifacts of this run (ZIP)';
    link.setAttribute('aria-label', link.title);
    return link;
  };

  function renderTasks() {
    const body = $('rj-tasks').tBodies[0];
    if (!state.tasks.length) {
      emptyRow(body, 'No Reporting Jobs yet.', 7);
      return;
    }
    body.replaceChildren(...state.tasks.map((task) => {
      const row = node('tr');
      if (!task.enabled) row.classList.add('rj-disabled');
      const artifacts = node('ul', undefined, 'rj-artifacts');
      task.artifacts.forEach((text) => artifacts.append(node('li', text)));
      const last = task.last_run;
      const lastCell = node('td');
      lastCell.append(statusBadge(last));
      if (last) lastCell.append(node('small', ` ${localTime(last.started_at || last.created_at)}`));
      const actions = node('div', undefined, 'table-actions');
      if (state.can_edit) {
        actions.append(actionButton('▶', 'Run now', async () => {
          await api(`/api/reporting/tasks/${task.id}/run`, {method: 'POST'});
          status(`${task.name} started.`, 'done'); await refresh();
        }));
      }
      if (last && last.artifacts.some((item) => item.status === 'ready')) actions.append(downloadLink(last));
      if (state.can_edit) {
        actions.append(
          actionButton('✎', 'Edit', async () => { await ensureOptions(); fillEditor(task); }),
          actionButton('⧉', 'Duplicate (disabled copy)', async () => {
            await api(`/api/reporting/tasks/${task.id}/duplicate`, {method: 'POST'});
            status(`${task.name} duplicated.`, 'done'); await refresh();
          }),
          actionButton(task.enabled ? '⏸' : '⏵', task.enabled ? 'Disable the schedule' : 'Enable the schedule', async () => {
            await api(`/api/reporting/tasks/${task.id}/enabled`, {method: 'POST', body: JSON.stringify({enabled: !task.enabled})});
            await refresh();
          }),
          actionButton('×', 'Delete the job and its runs', async () => {
            if (!window.confirm(`Delete ${task.name}, its run history and artifacts?`)) return;
            await api(`/api/reporting/tasks/${task.id}`, {method: 'DELETE'});
            status(`${task.name} deleted.`, 'done'); await refresh();
          }, 'danger-button icon-action'),
        );
      }
      row.append(
        node('td', task.name), cellWith(artifacts),
        node('td', task.enabled ? localTime(task.next_run_at) : 'Disabled'), node('td', task.recurrence),
        node('td', task.send_email ? `Yes · ${task.recipients.length} recipient${task.recipients.length === 1 ? '' : 's'}` : 'No'),
        lastCell, cellWith(actions),
      );
      row.cells[4].title = task.recipients.join(', ');
      return row;
    }));
  }

  function renderRuns() {
    const body = $('rj-runs').tBodies[0];
    if (!state.runs.length) {
      emptyRow(body, 'No runs yet.', 8);
      return;
    }
    body.replaceChildren(...state.runs.map((run) => {
      const row = node('tr');
      const statusCell = node('td');
      statusCell.append(statusBadge(run));
      if (['queued', 'running'].includes(run.status)) statusCell.append(node('small', ` ${run.progress}% · ${run.message}`));
      else if (run.error) statusCell.append(node('small', ` ${run.error}`, 'rj-error'));
      const artifacts = node('ul', undefined, 'rj-artifacts');
      run.artifacts.forEach((item, index) => {
        const entry = node('li');
        if (item.status === 'ready') {
          const link = node('a', item.title); link.href = `/api/reporting/runs/${run.id}/artifacts/${index}`; link.title = item.file_name;
          entry.append(link);
        } else {
          entry.append(node('span', `${item.title}: ${item.error || 'failed'}`, 'rj-error'));
        }
        artifacts.append(entry);
      });
      const actions = node('div', undefined, 'table-actions');
      if (run.artifacts.some((item) => item.status === 'ready')) actions.append(downloadLink(run));
      if (state.can_edit && !['queued', 'running'].includes(run.status)) {
        actions.append(actionButton('×', 'Delete this run and its artifacts', async () => {
          if (!window.confirm(`Delete run ${run.id} of ${run.task_name} and its artifacts?`)) return;
          await api(`/api/reporting/runs/${run.id}`, {method: 'DELETE'}); await refresh();
        }, 'danger-button icon-action'));
      }
      const cells = [node('td', String(run.id)), node('td', run.task_name), node('td', run.trigger === 'schedule' ? 'Schedule' : `Manual · ${run.requested_by}`),
        node('td', localTime(run.started_at || run.created_at)), statusCell, node('td', run.send_email ? (run.email_status || 'Pending') : 'No email')];
      row.append(...cells, cellWith(artifacts), cellWith(actions));
      return row;
    }));
  }

  async function refresh() {
    state = await api('/api/reporting/state');
    $('rj-new').hidden = !state.can_edit;
    renderTasks();
    renderRuns();
    clearTimeout(pollTimer);
    const active = state.runs.some((run) => ['queued', 'running'].includes(run.status));
    pollTimer = setTimeout(() => { void refresh().catch((error) => status(error.message, 'error')); }, active ? 4000 : 30000);
  }

  // -- events -------------------------------------------------------------
  document.addEventListener('change', (event) => {
    if (event.target.closest('#rj-form')) syncEditor();
  });
  $('rj-new').addEventListener('click', async () => {
    try { await ensureOptions(); fillEditor(null); } catch (error) { status(error.message, 'error'); }
  });
  $('rj-add-dashboard').addEventListener('click', () => {
    if (!options.dashboards.length) { status('There are no saved Dashboards in this workspace.', 'error'); return; }
    $('rj-dashboards').append(dashboardEntry());
  });
  $('rj-add-scoring').addEventListener('click', () => $('rj-scoring').append(scoringEntry()));
  $('rj-cancel').addEventListener('click', () => { $('rj-editor').hidden = true; editingId = null; });
  $('rj-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('rj-save');
    button.disabled = true;
    try {
      const payload = editorPayload();
      const result = await api(editingId ? `/api/reporting/tasks/${editingId}` : '/api/reporting/tasks', {
        method: editingId ? 'PUT' : 'POST', body: JSON.stringify(payload),
      });
      status(`${result.task.name} saved.`, 'done');
      $('rj-editor').hidden = true; editingId = null;
      await refresh();
    } catch (error) {
      status(error.message, 'error');
      window.alert(error.message);
    } finally {
      button.disabled = false;
    }
  });

  void refresh().catch((error) => status(error.message, 'error'));
})();
