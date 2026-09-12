/* Fast, dependency-free renderers for live E2E Dashboard chart payloads. */
(() => {
  'use strict';

  const palette = ['#6f42c1', '#de6b93', '#2f8f83', '#e08a3e', '#3f6fa7', '#8b5f3c', '#5f9e45', '#b84f5f'];
  const models = new WeakMap();
  const observed = new WeakSet();
  let resizeFrame = 0;

  const finite = value => Number.isFinite(Number(value));
  const numeric = values => values.map(Number).filter(Number.isFinite);
  const format = value => {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value ?? '');
    if (Math.abs(number) >= 1000) return number.toLocaleString(undefined, {maximumFractionDigits: 0});
    if (Math.abs(number) >= 100) return number.toFixed(0);
    if (Math.abs(number) >= 10) return number.toFixed(1).replace(/\.0$/, '');
    return number.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  };
  const shorten = (context, value, width) => {
    const text = String(value ?? '');
    if (context.measureText(text).width <= width) return text;
    let end = text.length;
    while (end > 2 && context.measureText(`${text.slice(0, end)}…`).width > width) end -= 1;
    return `${text.slice(0, end)}…`;
  };
  const extent = (values, fallback = [0, 1]) => {
    const clean = numeric(values);
    if (!clean.length) return fallback;
    let low = Math.min(...clean), high = Math.max(...clean);
    if (low === high) {
      const margin = Math.abs(low || 1) * 0.08;
      low -= margin; high += margin;
    }
    return [low, high];
  };
  const scale = (value, domain, range) => range[0] + ((Number(value) - domain[0]) / (domain[1] - domain[0] || 1)) * (range[1] - range[0]);

  function canvasContext(canvas) {
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(260, Math.round(bounds.width || canvas.parentElement?.clientWidth || 600));
    const height = Math.max(180, Math.round(bounds.height || canvas.parentElement?.clientHeight || 360));
    const pixelRatio = Math.min(globalThis.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * pixelRatio) || canvas.height !== Math.round(height * pixelRatio)) {
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
    }
    const context = canvas.getContext('2d');
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height);
    context.lineJoin = 'round'; context.lineCap = 'round';
    return {context, width, height};
  }

  function title(context, payload, width) {
    context.fillStyle = '#352747'; context.font = '700 13px system-ui, sans-serif'; context.textAlign = 'left';
    context.fillText(shorten(context, payload.title || 'Chart', width - 24), 12, 20);
  }

  function legend(context, series, left, top, width) {
    if (!series || series.length < 2) return 0;
    context.font = '10px system-ui, sans-serif'; context.textBaseline = 'middle';
    let x = left, y = top, rows = 1;
    for (let index = 0; index < series.length; index += 1) {
      const label = shorten(context, series[index].name || `Series ${index + 1}`, 105);
      const itemWidth = Math.min(130, context.measureText(label).width + 22);
      if (x + itemWidth > left + width && x > left) { x = left; y += 16; rows += 1; }
      if (rows > 2) break;
      context.fillStyle = palette[index % palette.length]; context.fillRect(x, y - 4, 9, 8);
      context.fillStyle = '#5b6874'; context.fillText(label, x + 13, y);
      x += itemWidth;
    }
    context.textBaseline = 'alphabetic';
    return Math.min(rows, 2) * 16;
  }

  function axes(context, plot, xDomain, yDomain, labels = {}) {
    context.strokeStyle = '#d7dee4'; context.lineWidth = 1; context.fillStyle = '#667580'; context.font = '9px system-ui, sans-serif';
    context.textAlign = 'right'; context.textBaseline = 'middle';
    for (let index = 0; index <= 4; index += 1) {
      const value = yDomain[0] + (yDomain[1] - yDomain[0]) * index / 4;
      const y = scale(value, yDomain, [plot.bottom, plot.top]);
      context.beginPath(); context.moveTo(plot.left, y); context.lineTo(plot.right, y); context.stroke();
      context.fillText(format(value), plot.left - 5, y);
    }
    context.strokeStyle = '#8797a2'; context.beginPath(); context.moveTo(plot.left, plot.top); context.lineTo(plot.left, plot.bottom); context.lineTo(plot.right, plot.bottom); context.stroke();
    context.textAlign = 'center'; context.textBaseline = 'top';
    for (let index = 0; index <= 2; index += 1) {
      const value = xDomain[0] + (xDomain[1] - xDomain[0]) * index / 2;
      context.fillText(format(value), scale(value, xDomain, [plot.left, plot.right]), plot.bottom + 5);
    }
    context.font = '600 9px system-ui, sans-serif'; context.fillStyle = '#52636f';
    if (labels.x) context.fillText(shorten(context, labels.x, plot.right - plot.left), (plot.left + plot.right) / 2, plot.bottom + 19);
    if (labels.y) {
      context.save(); context.translate(10, (plot.top + plot.bottom) / 2); context.rotate(-Math.PI / 2); context.textBaseline = 'top'; context.fillText(shorten(context, labels.y, plot.bottom - plot.top), 0, 0); context.restore();
    }
  }

  function linePlot(context, series, bounds, labels = {}, panelTitle = '') {
    if (panelTitle) { context.fillStyle = '#50435e'; context.font = '600 10px system-ui, sans-serif'; context.textAlign = 'left'; context.fillText(shorten(context, panelTitle, bounds.width), bounds.left, bounds.top + 10); }
    const legendHeight = legend(context, series, bounds.left + 42, bounds.top + (panelTitle ? 16 : 2), bounds.width - 48);
    const plot = {left: bounds.left + 43, right: bounds.left + bounds.width - 10, top: bounds.top + 12 + legendHeight + (panelTitle ? 12 : 0), bottom: bounds.top + bounds.height - 31};
    const xDomain = extent(series.flatMap(item => item.x || []));
    const yDomain = extent(series.flatMap(item => item.y || []), [0, 1]);
    if (yDomain[0] >= 0 && yDomain[1] <= 1.01) { yDomain[0] = 0; yDomain[1] = 1; }
    axes(context, plot, xDomain, yDomain, labels);
    series.forEach((item, seriesIndex) => {
      context.strokeStyle = palette[seriesIndex % palette.length]; context.lineWidth = 2; context.beginPath();
      (item.x || []).forEach((x, index) => {
        const y = item.y?.[index]; if (!finite(x) || !finite(y)) return;
        const px = scale(x, xDomain, [plot.left, plot.right]), py = scale(y, yDomain, [plot.bottom, plot.top]);
        if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
      });
      context.stroke();
    });
  }

  function categoryLabels(context, categories, plot, horizontal = false) {
    context.fillStyle = '#60707b'; context.font = '9px system-ui, sans-serif';
    if (horizontal) {
      context.textAlign = 'right'; context.textBaseline = 'middle';
      categories.forEach((item, index) => context.fillText(shorten(context, item, plot.left - 10), plot.left - 5, plot.top + (index + .5) * (plot.bottom - plot.top) / Math.max(categories.length, 1)));
      return;
    }
    context.textAlign = 'center'; context.textBaseline = 'top';
    const step = (plot.right - plot.left) / Math.max(categories.length, 1);
    const stride = Math.max(1, Math.ceil(categories.length / 12));
    categories.forEach((item, index) => { if (index % stride === 0) context.fillText(shorten(context, item, Math.max(step - 3, 35)), plot.left + (index + .5) * step, plot.bottom + 5); });
  }

  function verticalBars(context, payload, width, height) {
    const categories = payload.categories || [], series = payload.series || [];
    const legendHeight = legend(context, series, 54, 30, width - 70);
    const plot = {left: 52, right: width - 14, top: 36 + legendHeight, bottom: height - 38};
    const totals = categories.map((_item, categoryIndex) => series.reduce((sum, item) => sum + (finite(item.values?.[categoryIndex]) ? Number(item.values[categoryIndex]) : 0), 0));
    const maxValue = payload.type === 'stacked' && totals.every(value => value <= 100.001) ? 100 : Math.max(...totals, 1);
    axes(context, plot, [0, Math.max(categories.length, 1)], [0, maxValue], {y: payload.y_label});
    const step = (plot.right - plot.left) / Math.max(categories.length, 1), barWidth = Math.max(2, step * .72);
    categories.forEach((_category, categoryIndex) => {
      let accumulated = 0;
      series.forEach((item, seriesIndex) => {
        const value = finite(item.values?.[categoryIndex]) ? Number(item.values[categoryIndex]) : 0;
        const y0 = scale(accumulated, [0, maxValue], [plot.bottom, plot.top]); accumulated += value;
        const y1 = scale(accumulated, [0, maxValue], [plot.bottom, plot.top]);
        context.fillStyle = palette[seriesIndex % palette.length]; context.fillRect(plot.left + categoryIndex * step + (step - barWidth) / 2, y1, barWidth, Math.max(0, y0 - y1));
      });
    });
    categoryLabels(context, categories, plot);
  }

  function horizontalBars(context, payload, width, height) {
    const categories = payload.categories || [], series = payload.series || [];
    const labelWidth = Math.min(150, Math.max(65, width * .25));
    const legendHeight = legend(context, series, labelWidth + 8, 30, width - labelWidth - 20);
    const plot = {left: labelWidth, right: width - 16, top: 38 + legendHeight, bottom: height - 18};
    const totals = categories.map((_item, index) => series.reduce((sum, item) => sum + (Number(item.values?.[index]) || 0), 0));
    const xDomain = [0, Math.max(...totals, 1)];
    context.strokeStyle = '#d7dee4'; context.lineWidth = 1;
    for (let tick = 0; tick <= 4; tick += 1) { const x = scale(xDomain[1] * tick / 4, xDomain, [plot.left, plot.right]); context.beginPath(); context.moveTo(x, plot.top); context.lineTo(x, plot.bottom); context.stroke(); }
    const step = (plot.bottom - plot.top) / Math.max(categories.length, 1), barHeight = Math.max(2, step * .68);
    categories.forEach((_category, categoryIndex) => {
      let accumulated = 0;
      series.forEach((item, seriesIndex) => {
        const value = Number(item.values?.[categoryIndex]) || 0;
        const x0 = scale(accumulated, xDomain, [plot.left, plot.right]); accumulated += value;
        const x1 = scale(accumulated, xDomain, [plot.left, plot.right]);
        context.fillStyle = palette[seriesIndex % palette.length]; context.fillRect(x0, plot.top + categoryIndex * step + (step - barHeight) / 2, Math.max(0, x1 - x0), barHeight);
      });
    });
    categoryLabels(context, categories, plot, true);
  }

  function pointPlot(context, payload, width, height) {
    const series = payload.series || [], legendHeight = legend(context, series, 55, 30, width - 70);
    const plot = {left: 52, right: width - 14, top: 38 + legendHeight, bottom: height - 37};
    const allPoints = series.flatMap(item => item.points || []);
    const xDomain = extent(allPoints.map(point => point[0])), yDomain = extent(allPoints.map(point => point[1]));
    if (payload.type === 'map') {
      context.fillStyle = '#eef5f3'; context.fillRect(plot.left, plot.top, plot.right - plot.left, plot.bottom - plot.top);
      context.strokeStyle = '#d2e3df'; context.lineWidth = 1;
      for (let index = 1; index < 6; index += 1) { const x = plot.left + index * (plot.right - plot.left) / 6, y = plot.top + index * (plot.bottom - plot.top) / 6; context.beginPath(); context.moveTo(x, plot.top); context.lineTo(x, plot.bottom); context.moveTo(plot.left, y); context.lineTo(plot.right, y); context.stroke(); }
    }
    axes(context, plot, xDomain, yDomain, {x: payload.x_label, y: payload.y_label});
    series.forEach((item, seriesIndex) => {
      context.fillStyle = palette[seriesIndex % palette.length];
      (item.points || []).forEach(point => { if (!finite(point[0]) || !finite(point[1])) return; context.beginPath(); context.arc(scale(point[0], xDomain, [plot.left, plot.right]), scale(point[1], yDomain, [plot.bottom, plot.top]), 2.2, 0, Math.PI * 2); context.fill(); });
    });
  }

  function table(context, payload, width, height) {
    const headers = payload.headers || [], rows = payload.rows || [];
    if (!headers.length) return;
    const left = 12, top = 34, tableWidth = width - 24, rowHeight = Math.max(18, Math.min(26, (height - top - 8) / Math.max(rows.length + 1, 2))), columnWidth = tableWidth / headers.length;
    context.font = '600 10px system-ui, sans-serif'; context.textBaseline = 'middle';
    headers.forEach((value, index) => { context.fillStyle = '#e9e1f4'; context.fillRect(left + index * columnWidth, top, columnWidth, rowHeight); context.strokeStyle = '#d7cce7'; context.strokeRect(left + index * columnWidth, top, columnWidth, rowHeight); context.fillStyle = '#49375c'; context.textAlign = index ? 'center' : 'left'; context.fillText(shorten(context, value, columnWidth - 10), left + index * columnWidth + (index ? columnWidth / 2 : 5), top + rowHeight / 2); });
    context.font = '10px system-ui, sans-serif';
    rows.slice(0, Math.floor((height - top) / rowHeight) - 1).forEach((row, rowIndex) => row.forEach((value, columnIndex) => { const x = left + columnIndex * columnWidth, y = top + (rowIndex + 1) * rowHeight; context.fillStyle = rowIndex % 2 ? '#ffffff' : '#f7f5fa'; context.fillRect(x, y, columnWidth, rowHeight); context.strokeStyle = '#e3dfea'; context.strokeRect(x, y, columnWidth, rowHeight); context.fillStyle = '#52616b'; context.textAlign = columnIndex ? 'center' : 'left'; context.fillText(shorten(context, value ?? '—', columnWidth - 10), x + (columnIndex ? columnWidth / 2 : 5), y + rowHeight / 2); }));
  }

  function draw(canvas, payload) {
    const {context, width, height} = canvasContext(canvas);
    title(context, payload, width);
    if (!payload || payload.type === 'empty') {
      context.fillStyle = '#756781'; context.font = '13px system-ui, sans-serif'; context.textAlign = 'center'; context.textBaseline = 'middle';
      context.fillText(shorten(context, payload?.message || 'No chart data available', width - 40), width / 2, height / 2);
      return;
    }
    if (payload.type === 'line') linePlot(context, payload.series || [], {left: 0, top: 24, width, height: height - 24}, {x: payload.x_label, y: payload.y_label});
    else if (payload.type === 'multi_line') {
      const panels = payload.panels || [], columns = panels.length > 1 ? 2 : 1, rows = Math.max(1, Math.ceil(panels.length / columns));
      panels.forEach((panel, index) => linePlot(context, panel.series || [], {left: (index % columns) * width / columns, top: 24 + Math.floor(index / columns) * (height - 24) / rows, width: width / columns, height: (height - 24) / rows}, {x: panel.x_label, y: 'CDF'}, panel.title));
    } else if (payload.type === 'bar' || payload.type === 'stacked') verticalBars(context, payload, width, height);
    else if (payload.type === 'horizontal_stacked') horizontalBars(context, payload, width, height);
    else if (payload.type === 'scatter' || payload.type === 'map') pointPlot(context, payload, width, height);
    else if (payload.type === 'table') table(context, payload, width, height);
  }

  const resizeObserver = 'ResizeObserver' in globalThis ? new ResizeObserver(entries => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => entries.forEach(entry => {
      const payload = models.get(entry.target);
      if (payload) draw(entry.target, payload);
    }));
  }) : null;

  globalThis.renderDashboardChart = (canvas, payload) => {
    models.set(canvas, payload);
    draw(canvas, payload);
    if (resizeObserver && !observed.has(canvas)) { observed.add(canvas); resizeObserver.observe(canvas); }
  };
})();
