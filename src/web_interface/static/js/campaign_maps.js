/* Workspace Config → Campaign Maps: label format, order of the radio modes and exceptions. */
(() => {
  'use strict';

  const root = document.querySelector('[data-campaign-maps]');
  if (!root) return;

  const DEFAULT_MAP = {format: '{year}-Q{quarter}{-mode}', mode_order: ['', 'NSA', 'SA'], exceptions: []};
  const MODE_LABELS = {'': 'Without mode (for example 2026-Q2)', NSA: 'NSA', SA: 'SA'};
  const $ = (selector) => root.querySelector(selector);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const readJson = (id, fallback) => {
    try { return JSON.parse(document.getElementById(id)?.textContent || 'null') ?? fallback; } catch (_error) { return fallback; }
  };
  const campaigns = readJson('campaign-map-campaigns', []);
  const saved = {...DEFAULT_MAP, ...(readJson('campaign-map', {}) || {})};

  const iconButton = (label, title, action) => {
    const button = node('button', label, 'icon-action');
    button.type = 'button';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.addEventListener('click', action);
    return button;
  };
  const moveButtons = (item, after) => [
    iconButton('↑', 'Move up', () => { item.previousElementSibling?.before(item); after(); }),
    iconButton('↓', 'Move down', () => { item.nextElementSibling?.after(item); after(); }),
  ];

  const renderModes = (modes) => {
    $('[data-campaign-modes]').replaceChildren(...modes.map((mode) => {
      const item = node('li', undefined, 'campaign-map-mode');
      item.dataset.mode = mode;
      item.append(node('span', MODE_LABELS[mode] ?? mode), ...moveButtons(item, schedulePreview));
      return item;
    }));
  };
  const exceptionRow = (exception = {label: '', sources: []}) => {
    const row = node('tr');
    const order = node('td');
    order.dataset.label = 'Order';
    order.append(node('div', undefined, 'mapping-order-actions'));
    order.firstChild.append(...moveButtons(row, schedulePreview));
    const label = node('input', undefined, 'table-input');
    label.type = 'text';
    label.maxLength = 80;
    label.value = exception.label || '';
    label.placeholder = 'Label, for example 2025-Q4 Xmas';
    label.setAttribute('aria-label', 'Exception label');
    const sources = node('textarea', undefined, 'operator-mapping-aliases');
    sources.rows = 2;
    sources.value = (exception.sources || []).join('\n');
    sources.placeholder = 'One source campaign per line';
    sources.setAttribute('aria-label', 'Source campaigns');
    [label, sources].forEach((field) => field.addEventListener('input', schedulePreview));
    const actions = node('td');
    actions.append(iconButton('×', 'Remove this exception', () => { row.remove(); schedulePreview(); }));
    actions.firstChild.classList.add('danger-button');
    const labelCell = node('td');
    labelCell.append(label);
    const sourcesCell = node('td');
    sourcesCell.append(sources);
    row.append(order, labelCell, sourcesCell, actions);
    return row;
  };
  const fill = (map) => {
    $('[data-campaign-format]').value = map.format || DEFAULT_MAP.format;
    renderModes(map.mode_order?.length ? map.mode_order : DEFAULT_MAP.mode_order);
    $('[data-campaign-exceptions]').replaceChildren(...(map.exceptions || []).map(exceptionRow));
    schedulePreview();
  };
  const collect = () => ({
    format: $('[data-campaign-format]').value.trim(),
    mode_order: [...root.querySelectorAll('[data-campaign-modes] [data-mode]')].map((item) => item.dataset.mode),
    exceptions: [...root.querySelectorAll('[data-campaign-exceptions] tr')].map((row) => ({
      label: row.querySelector('input').value.trim(),
      sources: row.querySelector('textarea').value.split(/\n/).map((value) => value.trim()).filter(Boolean),
    })).filter((item) => item.label || item.sources.length),
  });

  const message = (text, tone = '') => {
    const element = $('[data-campaign-message]');
    element.textContent = text;
    element.className = `campaign-map-message${tone ? ` is-${tone}` : ''}`;
  };
  const request = async (url, method, map) => {
    const response = await fetch(url, {method, credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({campaign_map: map})});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The Campaign Maps could not be saved.');
    return payload;
  };
  const renderPreview = (preview) => {
    const host = $('[data-campaign-preview]');
    if (!preview.length) {
      host.replaceChildren(node('p', 'No campaigns in the ready CDRs of this workspace yet.', 'form-note'));
      return;
    }
    const table = node('table', undefined, 'operator-mappings-table campaign-map-preview-table');
    const head = node('tr');
    ['#', 'Label', 'Source campaign'].forEach((text) => head.append(node('th', text)));
    table.append(node('thead'), node('tbody'));
    table.tHead.append(head);
    preview.forEach((item, index) => {
      const row = node('tr');
      row.append(node('td', String(index + 1)), node('td', item.label, 'campaign-map-label'), node('td', item.campaign));
      table.tBodies[0].append(row);
    });
    host.replaceChildren(table);
  };
  let previewTimer = 0;
  let previewToken = 0;
  function schedulePreview() {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(async () => {
      const token = ++previewToken;
      try {
        const payload = await request('/api/workspace-config/campaign-map/preview', 'POST', collect());
        if (token !== previewToken) return;
        renderPreview(payload.preview || []);
        if ($('[data-campaign-message]').classList.contains('is-error')) message('');
      } catch (error) {
        if (token === previewToken) message(error.message, 'error');
      }
    }, 250);
  }

  $('[data-campaign-format]').addEventListener('input', schedulePreview);
  // A saved message no longer applies once the map is edited again.
  root.addEventListener('input', () => {
    if ($('[data-campaign-message]').classList.contains('is-success')) message('');
  });
  $('[data-campaign-exception-add]').addEventListener('click', () => {
    const row = exceptionRow();
    $('[data-campaign-exceptions]').append(row);
    row.querySelector('input').focus();
  });
  $('[data-campaign-default]').addEventListener('click', () => {
    fill(DEFAULT_MAP);
    message('Default map filled in: Save to apply it.');
  });
  $('[data-campaign-save]').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const payload = await request('/api/workspace-config/campaign-map', 'PUT', collect());
      globalThis.setCampaignMap?.(payload.campaign_map);
      fill(payload.campaign_map);
      message('Campaign Maps saved: every chart, table, filter and report uses them.', 'success');
    } catch (error) {
      message(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });
  fill(saved);
  if (!campaigns.length) renderPreview([]);
})();
