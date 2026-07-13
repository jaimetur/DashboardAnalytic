function drawLineChart(svg, labels, series, width, height, padding) {
  const minX = Math.min(...labels);
  const maxX = Math.max(...labels);
  const scaleX = (value) => padding + ((value - minX) / ((maxX - minX) || 1)) * (width - padding * 2);
  const scaleY = (value) => height - padding - value * (height - padding * 2);
  const points = labels.map((label, index) => `${scaleX(label)},${scaleY(series[index])}`).join(' ');
  svg.innerHTML = `
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#9ab0bc" />
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="#9ab0bc" />
    <polyline fill="none" stroke="#0b7a75" stroke-width="3" points="${points}" />
    <text x="${padding}" y="18" fill="#526371">CDF</text>
  `;
}

function drawBarChart(svg, labels, series, width, height, padding) {
  const maxValue = Math.max(...series, 1);
  const barWidth = (width - padding * 2) / labels.length;
  const bars = labels.map((label, index) => {
    const value = series[index];
    const scaledHeight = ((value || 0) / maxValue) * (height - padding * 2);
    const x = padding + index * barWidth + 8;
    const y = height - padding - scaledHeight;
    const textX = x + Math.max(barWidth - 16, 24) / 2;
    return `
      <rect x="${x}" y="${y}" width="${Math.max(barWidth - 16, 24)}" height="${scaledHeight}" rx="10" fill="#dd653e"></rect>
      <text x="${textX}" y="${height - 10}" text-anchor="middle" fill="#526371" font-size="11">${String(label).slice(0, 12)}</text>
    `;
  }).join('');
  svg.innerHTML = `
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#9ab0bc" />
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="#9ab0bc" />
    ${bars}
  `;
}

function drawChart(container) {
  const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[],"type":"line"}');
  const svg = container.querySelector('.chart-svg');
  const labels = payload.labels || [];
  const series = payload.series || [];
  if (!svg || labels.length === 0 || series.length === 0) {
    if (svg) {
      svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#526371">No chart data available</text>';
    }
    return;
  }
  const width = 600;
  const height = 280;
  const padding = 34;
  if (payload.type === 'bar') {
    drawBarChart(svg, labels, series, width, height, padding);
    return;
  }
  drawLineChart(svg, labels, series, width, height, padding);
}

document.querySelectorAll('[data-chart]').forEach(drawChart);

document.querySelectorAll('.collapsible-panel').forEach((panel) => {
  const chip = panel.querySelector('.collapse-chip');
  const updateChip = () => {
    if (!chip) return;
    chip.textContent = panel.open ? 'Collapse' : 'Expand';
  };
  updateChip();
  panel.addEventListener('toggle', updateChip);
});

const loadingOverlay = document.getElementById('loading-overlay');
const loadingTitle = document.getElementById('loading-title');
const loadingCopy = document.getElementById('loading-copy');
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmTitle = document.getElementById('confirm-title');
const confirmCopy = document.getElementById('confirm-copy');
const confirmAccept = document.getElementById('confirm-accept');
const confirmCancel = document.getElementById('confirm-cancel');
const filePickerInput = document.querySelector('[data-file-picker-input]');
const filePickerText = document.querySelector('[data-file-picker-text]');
const inputKindSelect = document.querySelector('[data-input-kind-select]');
const datasetSelect = document.querySelector('[data-dataset-select]');

function hideLoadingOverlay() {
  if (!loadingOverlay) return;
  loadingOverlay.hidden = true;
  document.body.classList.remove('loading-active');
}

function showLoadingOverlay(label) {
  if (!loadingOverlay) return;
  loadingTitle.textContent = label || 'Processing request';
  loadingCopy.textContent = 'Please wait while the workspace processes the selected dataset or updates the dashboard.';
  loadingOverlay.hidden = false;
  document.body.classList.add('loading-active');
}

hideLoadingOverlay();
window.addEventListener('pageshow', hideLoadingOverlay);

document.querySelectorAll('form[data-loading-label]').forEach((form) => {
  form.addEventListener('submit', () => {
    showLoadingOverlay(form.dataset.loadingLabel);
  });
});

function showConfirmDialog(message, options = {}) {
  if (!confirmOverlay || !confirmTitle || !confirmCopy || !confirmAccept || !confirmCancel) {
    return Promise.resolve(window.confirm(message || 'Are you sure?'));
  }

  confirmTitle.textContent = options.title || 'Confirm action';
  confirmCopy.textContent = message || options.copy || 'Are you sure you want to continue?';
  confirmAccept.textContent = options.confirmLabel || 'Confirm';
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
      resolve(accepted);
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

document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const accepted = await showConfirmDialog(form.dataset.confirm, {
      title: 'Delete user',
      confirmLabel: 'Delete user',
    });
    if (accepted) {
      form.submit();
    }
  });
});

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
}

const queueNode = document.querySelector('[data-queue-status-url]');
if (queueNode) {
  const url = queueNode.dataset.queueStatusUrl || '';
  const delay = Number(queueNode.dataset.queuePollMs || '0');
  const selectedDatasetField = document.querySelector('input[name="dataset_id"], select[name="dataset_id"]');
  const waitingPanel = document.querySelector('.queue-waiting-copy');

  const updateQueueRow = (dataset) => {
    const row = document.querySelector(`[data-dataset-row][data-dataset-id="${dataset.id}"]`);
    if (!row) return;
    const kind = row.querySelector('[data-queue-kind]');
    const rows = row.querySelector('[data-queue-rows]');
    const statusPill = row.querySelector('[data-queue-status-pill]');
    const progressBar = row.querySelector('[data-queue-progress-bar]');
    const progressLabel = row.querySelector('[data-queue-progress-label]');
    const updated = row.querySelector('[data-queue-updated]');

    if (kind) kind.textContent = dataset.input_kind_label || 'Other';
    if (rows) rows.textContent = String(dataset.row_count || 0);
    if (statusPill) {
      statusPill.textContent = dataset.status_label || dataset.status || 'Queued';
      statusPill.className = `queue-status-pill queue-status-${dataset.status}`;
    }
    if (progressBar) {
      progressBar.style.width = `${dataset.progress || 0}%`;
      progressBar.className = `progress-bar status-${dataset.status}`;
    }
    if (progressLabel) progressLabel.textContent = `${dataset.progress || 0}%`;
    if (updated) updated.textContent = dataset.updated_at || dataset.uploaded_at || '';
  };

  const pollQueue = async () => {
    try {
      const response = await fetch(url, {headers: {'Accept': 'application/json'}});
      if (!response.ok) return;
      const payload = await response.json();
      const datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
      datasets.forEach(updateQueueRow);
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
