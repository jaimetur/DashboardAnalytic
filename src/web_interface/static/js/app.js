function drawChart(container) {
  const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[]}');
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
  const padding = 30;
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
document.querySelectorAll('[data-chart]').forEach(drawChart);
