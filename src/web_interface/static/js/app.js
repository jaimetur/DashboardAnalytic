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

const autoRefreshNode = document.querySelector('[data-autorefresh]');
if (autoRefreshNode) {
  const delay = Number(autoRefreshNode.dataset.autorefresh || '0');
  if (delay > 0) {
    window.setTimeout(() => window.location.reload(), delay);
  }
}
