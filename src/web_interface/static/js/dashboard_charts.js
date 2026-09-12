/* Browser painter for report-faithful E2E Dashboard chart models. */
(() => {
  'use strict';

  const LOGICAL_WIDTH = 1600;
  const LOGICAL_HEIGHT = 900;
  const FONT_FAMILY = 'Arial, sans-serif';
  const models = new WeakMap();
  const views = new WeakMap();
  const cameraStates = new WeakMap();
  const nativeFillTexts = new WeakMap();
  const renderStates = new WeakMap();
  const observed = new WeakSet();
  const mapTiles = new Map();
  const mapWaits = new WeakMap();
  let resizeFrame = 0;

  const finite = value => Number.isFinite(Number(value));
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const font = (context, size, bold = false) => { context.font = `${bold ? '700 ' : ''}${size}px ${FONT_FAMILY}`; };
  const line = (context, x1, y1, x2, y2, colour = '#AEBBC4', width = 1) => {
    context.save(); context.strokeStyle = colour; context.lineWidth = width;
    context.beginPath(); context.moveTo(x1, y1); context.lineTo(x2, y2); context.stroke(); context.restore();
  };
  const textWidth = (context, value) => context.measureText(String(value)).width;
  const displayKey = key => (key || []).filter(value => value !== '(all)').join(' · ') || '(all)';
  const percent = value => `${(Number(value) * 100).toFixed(1)}%`;
  const numericLabel = value => {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value ?? '');
    if (Math.abs(number) >= 1000) return number.toLocaleString(undefined, {maximumFractionDigits: 0});
    return number.toFixed(2);
  };
  const transformPoint = (transform, x, y) => ({x: transform.x + x * transform.scale, y: transform.y + y * transform.scale});
  const pushRectangleHit = (state, transform, rectangle, details) => {
    const start = transformPoint(transform, rectangle.x, rectangle.y);
    state.hits.push({kind: 'rectangle', x: start.x, y: start.y, width: rectangle.width * transform.scale, height: rectangle.height * transform.scale, ...details});
  };
  const pushPointHit = (state, transform, x, y, details) => {
    const point = transformPoint(transform, x, y);
    state.hits.push({kind: 'point', x: point.x, y: point.y, ...details});
  };
  const pushLineHit = (state, transform, points, details) => {
    state.hits.push({kind: 'line', points: points.map(point => ({...point, ...transformPoint(transform, point.x, point.y)})), ...details});
  };

  function osmWorldCoordinates(latitude, longitude, zoom) {
    const boundedLatitude = clamp(Number(latitude), -85.05112878, 85.05112878);
    const scale = 256 * (2 ** Number(zoom));
    const x = (Number(longitude) + 180) / 360 * scale;
    const radians = boundedLatitude * Math.PI / 180;
    const y = (1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * scale;
    return [x, y];
  }

  function mapTileRecord(url) {
    if (mapTiles.has(url)) return mapTiles.get(url);
    const image = new Image();
    const record = {image, status: 'loading'};
    record.promise = new Promise(resolve => {
      image.addEventListener('load', () => { record.status = 'ready'; resolve(record); }, {once: true});
      image.addEventListener('error', () => { record.status = 'error'; resolve(record); }, {once: true});
    });
    image.decoding = 'async';
    image.src = url;
    mapTiles.set(url, record);
    return record;
  }

  function mapTileRecords(canvas, payload) {
    const basemap = payload.basemap, range = basemap?.tile_range;
    if (!basemap || !Array.isArray(range) || range.length !== 4) return [];
    const [left, top, right, bottom] = range.map(Number), records = [];
    for (let y = top; y <= bottom; y += 1) {
      for (let x = left; x <= right; x += 1) {
        const url = String(basemap.url_template || '')
          .replace('{z}', String(basemap.zoom)).replace('{x}', String(x)).replace('{y}', String(y));
        records.push({x, y, ...mapTileRecord(url)});
      }
    }
    const pending = records.filter(record => record.status === 'loading');
    const signature = `${basemap.zoom}:${range.join(':')}`;
    const waiting = mapWaits.get(canvas);
    if (pending.length && (waiting?.signature !== signature || waiting?.payload !== payload)) {
      mapWaits.set(canvas, {signature, payload});
      Promise.all(pending.map(record => record.promise)).then(() => {
        if (mapWaits.get(canvas)?.payload === payload) mapWaits.delete(canvas);
        if (models.get(canvas) === payload) draw(canvas, payload);
      });
    }
    return records;
  }

  function cameraFor(canvas) {
    let camera = cameraStates.get(canvas);
    if (!camera) {
      camera = {zoom: 1, panX: 0, panY: 0};
      cameraStates.set(canvas, camera);
    }
    return camera;
  }

  function constrainCamera(camera) {
    camera.zoom = clamp(Number(camera.zoom) || 1, 1, 4);
    if (camera.zoom === 1) {
      camera.panX = 0;
      camera.panY = 0;
      return camera;
    }
    const maximumX = LOGICAL_WIDTH * (camera.zoom - 1) / 2;
    const maximumY = LOGICAL_HEIGHT * (camera.zoom - 1) / 2;
    camera.panX = clamp(Number(camera.panX) || 0, -maximumX, maximumX);
    camera.panY = clamp(Number(camera.panY) || 0, -maximumY, maximumY);
    return camera;
  }

  function prepareCanvas(canvas) {
    const bounds = canvas.getBoundingClientRect();
    const cssWidth = Math.max(1, bounds.width || canvas.parentElement?.clientWidth || 600);
    const cssHeight = Math.max(1, bounds.height || canvas.parentElement?.clientHeight || 360);
    const pixelRatio = Math.min(globalThis.devicePixelRatio || 1, 2);
    const backingWidth = Math.round(cssWidth * pixelRatio), backingHeight = Math.round(cssHeight * pixelRatio);
    if (canvas.width !== backingWidth || canvas.height !== backingHeight) { canvas.width = backingWidth; canvas.height = backingHeight; }
    const context = canvas.getContext('2d');
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0); context.clearRect(0, 0, cssWidth, cssHeight);
    context.fillStyle = '#FFFFFF'; context.fillRect(0, 0, cssWidth, cssHeight);
    const scaleX = cssWidth / LOGICAL_WIDTH, scaleY = cssHeight / LOGICAL_HEIGHT;
    const camera = cameraFor(canvas);
    constrainCamera(camera);
    const originX = (1 - camera.zoom) * LOGICAL_WIDTH / 2 + camera.panX;
    const originY = (1 - camera.zoom) * LOGICAL_HEIGHT / 2 + camera.panY;
    context.setTransform(
      pixelRatio * scaleX * camera.zoom, 0, 0, pixelRatio * scaleY * camera.zoom,
      pixelRatio * scaleX * originX, pixelRatio * scaleY * originY,
    );
    let nativeFillText = nativeFillTexts.get(context);
    if (!nativeFillText) {
      nativeFillText = context.fillText.bind(context);
      nativeFillTexts.set(context, nativeFillText);
    }
    context.fillText = (value, x, y, maximumWidth) => {
      const transform = context.getTransform();
      const textScale = Math.min(Math.hypot(transform.a, transform.b), Math.hypot(transform.c, transform.d));
      const pointX = transform.a * x + transform.c * y + transform.e;
      const pointY = transform.b * x + transform.d * y + transform.f;
      const angle = Math.atan2(transform.b, transform.a);
      context.save();
      context.setTransform(textScale * Math.cos(angle), textScale * Math.sin(angle), -textScale * Math.sin(angle), textScale * Math.cos(angle), pointX, pointY);
      if (maximumWidth === undefined) nativeFillText(value, 0, 0);
      else nativeFillText(value, 0, 0, maximumWidth);
      context.restore();
    };
    context.lineJoin = 'round'; context.lineCap = 'round'; context.textBaseline = 'top';
    views.set(canvas, {scaleX, scaleY, zoom: camera.zoom, originX, originY});
    return context;
  }

  function drawTitle(context, title) {
    context.fillStyle = '#1D3345'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, 40, true);
    context.fillText(String(title || ''), 32, 20);
  }

  function fittedText(context, value, width) {
    const full = String(value ?? '');
    if (textWidth(context, full) <= width) return full;
    let result = '';
    for (const character of full) { if (textWidth(context, result + character + '…') > width) break; result += character; }
    return `${result.trimEnd()}…`;
  }

  function rotatedLabel(context, value, centreX, bottomY, colour, size, bold = true) {
    context.save(); context.translate(centreX, bottomY); context.rotate(-Math.PI / 4);
    context.fillStyle = colour; context.textAlign = 'center'; context.textBaseline = 'bottom'; font(context, size, bold);
    context.fillText(String(value), 0, 0); context.restore();
  }

  function verticalLabel(context, value, centreX, centreY, colour, size, bold = true) {
    context.save(); context.translate(centreX, centreY); context.rotate(-Math.PI / 2);
    context.fillStyle = colour; context.textAlign = 'center'; context.textBaseline = 'middle'; font(context, size, bold);
    context.fillText(String(value), 0, 0); context.restore();
  }

  function dashedVertical(context, x, top, bottom) {
    context.save(); context.setLineDash([8, 6]); line(context, x, top, x, bottom, '#AEBBC4', 1); context.restore();
  }

  function dashedHorizontal(context, y, left, right) {
    context.save(); context.setLineDash([8, 6]); line(context, left, y, right, y, '#AEBBC4', 1); context.restore();
  }

  function hierarchySpans(keys, level) {
    const spans = []; let start = 0;
    while (start < keys.length) {
      let end = start + 1; const prefix = keys[start].slice(0, level + 1).join('\u001f');
      while (end < keys.length && keys[end].slice(0, level + 1).join('\u001f') === prefix) end += 1;
      spans.push([start, end, String(keys[start][level] ?? '')]); start = end;
    }
    return spans;
  }

  function drawTopColumnSeparators(context, keys, axisColumns, left, width, top, bottom) {
    if (keys.length < 2) return;
    const level = axisColumns.findIndex(column => String(column).startsWith('__catalog_column_'));
    if (level < 0) return;
    for (let index = 1; index < keys.length; index += 1) {
      if (String(keys[index][level]) !== String(keys[index - 1][level])) dashedVertical(context, left + index * width / keys.length, top, bottom);
    }
  }

  function drawHierarchicalAxisLabels(context, keys, left, width, top, bottom) {
    if (!keys.length) return;
    const levels = keys[0].length, itemWidth = width / keys.length;
    let rotate = false; font(context, 18, true);
    for (let level = 0; level < Math.max(levels - 1, 0); level += 1) {
      for (const [start, end, value] of hierarchySpans(keys, level)) {
        if (textWidth(context, value.slice(0, 20)) + 12 > (end - start) * itemWidth) rotate = true;
      }
    }
    font(context, 16, true);
    if (keys.some(key => textWidth(context, String(key.at(-1)).slice(0, 18)) + 8 > itemWidth)) rotate = true;
    for (let level = 0; level < Math.max(levels - 1, 0); level += 1) {
      for (const [start, end, rawValue] of hierarchySpans(keys, level)) {
        const centre = left + ((start + end) / 2) * itemWidth, value = rawValue.slice(0, 20), y = top - 30 * (levels - level);
        if (rotate) rotatedLabel(context, value, centre, y + 24, '#566A78', 18);
        else { context.fillStyle = '#566A78'; context.textAlign = 'center'; context.textBaseline = 'top'; font(context, 18, true); context.fillText(value, centre, y); }
        line(context, left + start * itemWidth, y + 24, left + end * itemWidth, y + 24, '#CDD7DE', 1);
      }
    }
    keys.forEach((key, index) => {
      const value = String(key.at(-1) ?? '').slice(0, 18), centre = left + (index + .5) * itemWidth;
      if (rotate) rotatedLabel(context, value, centre, bottom + 78, '#62727E', 16);
      else { context.fillStyle = '#62727E'; context.textAlign = 'center'; context.textBaseline = 'top'; font(context, 16, true); context.fillText(value, centre, bottom + 11); }
    });
  }

  function drawLegend(context, legend, options = {}) {
    const items = legend?.items || []; let position = String(legend?.position || 'none').toLowerCase();
    if (!items.length || position === 'none') return;
    if (!['top', 'bottom', 'left', 'right'].includes(position)) position = 'top';
    const lineMarkers = Boolean(legend.line_markers), size = Math.max(Number(options.fontSize || 15), 17), markerSize = 22;
    const legendLineWidth = width => Math.max(Number(width) > 1 ? Number(width) + 2 : Number(width), 3);
    if (position === 'top' || position === 'bottom') {
      const columns = lineMarkers ? Math.min(Math.max(items.length, 1), 6) : 5, rowHeight = size + 12;
      const rows = Math.max(1, Math.ceil(items.length / columns)), startY = position === 'top' ? 80 : 900 - rows * rowHeight - 8;
      items.forEach((item, index) => {
        const x = 100 + (index % columns) * (lineMarkers ? 1400 / columns : 275), y = startY + Math.floor(index / columns) * rowHeight;
        const textOnly = !item.colour;
        if (lineMarkers && !textOnly) line(context, x, y + 11, x + 34, y + 11, item.colour, legendLineWidth(item.width));
        else if (!textOnly) { context.fillStyle = item.colour; context.fillRect(x, y, markerSize, markerSize); }
        context.fillStyle = '#263B4A'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, size, true);
        context.fillText(String(item.label).slice(0, 28), textOnly ? x : x + (lineMarkers ? 43 : 32), y - 1);
      });
      return;
    }
    const x = options.sideX ?? (position === 'left' ? 26 : 1380);
    items.forEach((item, index) => {
      const y = 112 + index * (size + 14), textOnly = !item.colour;
      if (lineMarkers && !textOnly) line(context, x, y + 11, x + 34, y + 11, item.colour, legendLineWidth(item.width));
      else if (!textOnly) { context.fillStyle = item.colour; context.fillRect(x, y, markerSize, markerSize); }
      context.fillStyle = '#263B4A'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, size, true);
      context.fillText(String(item.label).slice(0, 24), textOnly ? x : x + (lineMarkers ? 43 : 32), y - 1);
    });
  }

  function drawStatus(context, payload, state, transform) {
    const states = payload.states || [];
    if (payload.mode === 'flat') {
      const categories = payload.categories || [], left = 145, top = 115, width = 1300, height = 640;
      const barWidth = Math.max(20, Math.min(72, Math.floor(width / Math.max(categories.length * 2, 1))));
      categories.forEach((category, index) => {
        const ratios = payload.cells[index] || [], x = left + index * width / categories.length + 12; let running = 0;
        states.forEach((series, seriesIndex) => {
          const ratio = Number(ratios[seriesIndex] || 0), segmentHeight = ratio * height, y = top + height - running - segmentHeight;
          context.fillStyle = series.colour; context.fillRect(x, y, barWidth, segmentHeight);
          if (ratio >= .08) { context.fillStyle = '#FFFFFF'; context.textAlign = 'left'; font(context, 16, true); context.fillText(percent(ratio), x + 2, y + segmentHeight / 2 - 8); }
          else if (ratio >= .005) { context.fillStyle = series.colour; font(context, 12, true); context.fillText(percent(ratio), x + barWidth + 3, Math.max(top, y - 7)); }
          if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: category, series: series.name, value: percent(ratio)});
          running += segmentHeight;
        });
        const label = String(category).slice(0, 24); font(context, 18, true);
        if (textWidth(context, label) > width / categories.length - 8) rotatedLabel(context, label, x + barWidth / 2, top + height + 75, '#5A6B78', 18);
        else { context.fillStyle = '#5A6B78'; context.textAlign = 'left'; context.fillText(label, x - 4, top + height + 8); }
      });
      for (let tick = 0; tick <= 100; tick += 20) {
        const y = top + height - tick / 100 * height; line(context, left - 20, y, left + width, y, '#E4E9ED');
        context.fillStyle = '#4E6271'; context.textAlign = 'left'; font(context, 18, true); context.fillText(`${tick}%`, 64, y - 10);
      }
      drawLegend(context, payload.legend, {fontSize: 16}); return;
    }

    const rowKeys = payload.row_keys || [[]], columnKeys = payload.column_keys || [];
    font(context, 18, true);
    const rowLabelWidths = (rowKeys[0] || []).map((_value, level) => Math.max(...rowKeys.map(key => textWidth(context, String(key[level] ?? '').slice(0, 24))), 0) + 18);
    const chartLeft = Math.max(145, Math.min(540, 24 + Math.min(rowLabelWidths.reduce((sum, value) => sum + value, 0), 420) + 68));
    const chartTop = 245, chartRight = 1395, chartHeight = 510, chartWidth = chartRight - chartLeft;
    const rowHeight = chartHeight / rowKeys.length, columnWidth = chartWidth / columnKeys.length, barWidth = Math.max(18, Math.min(86, columnWidth * .68));
    const upperLevels = Math.max((columnKeys[0]?.length || 1) - 1, 0), headerBandHeight = Math.min(32, 112 / Math.max(upperLevels, 1));
    const headerTop = chartTop - upperLevels * headerBandHeight - 8; font(context, 15, true);
    for (let level = 0; level < upperLevels; level += 1) {
      const bandTop = headerTop + level * headerBandHeight;
      hierarchySpans(columnKeys, level).forEach(([start, end, value]) => {
        const left = chartLeft + start * columnWidth, right = chartLeft + end * columnWidth, caption = fittedText(context, value, right - left - 10);
        context.fillStyle = '#405765'; context.textAlign = 'center'; context.fillText(caption, (left + right) / 2, bandTop + 2);
        line(context, left, bandTop + headerBandHeight - 3, right, bandTop + headerBandHeight - 3, '#BCC8D0');
      });
    }
    for (let index = 1; index < columnKeys.length; index += 1) {
      let changed = columnKeys[index - 1].findIndex((value, level) => value !== columnKeys[index][level]);
      if (changed < 0) changed = columnKeys[index].length - 1;
      const x = chartLeft + index * columnWidth, lineTop = headerTop + Math.min(changed, upperLevels) * headerBandHeight;
      if (changed === 0) line(context, x, lineTop, x, chartTop + chartHeight, '#AEBBC4', 2); else dashedVertical(context, x, lineTop, chartTop + chartHeight);
    }
    rowKeys.forEach((rowKey, rowIndex) => {
      const paneTop = chartTop + rowIndex * rowHeight, paneBottom = paneTop + rowHeight, next = rowKeys[rowIndex + 1];
      if (!next || !rowKey.length || rowKey[0] !== next[0]) line(context, 24, paneBottom, chartLeft + chartWidth, paneBottom, '#AEBBC4', 2);
      else dashedHorizontal(context, paneBottom, 24, chartLeft + chartWidth);
      (rowIndex === rowKeys.length - 1 ? [0, 50, 100] : [50, 100]).forEach(tick => {
        const y = paneBottom - tick / 100 * rowHeight; line(context, chartLeft, y, chartLeft + chartWidth, y, '#E8ECEF');
        context.fillStyle = '#566A78'; context.textAlign = 'left'; font(context, 15, true); context.fillText(`${tick}%`, chartLeft - 50, y - 9);
      });
      columnKeys.forEach((columnKey, columnIndex) => {
        const ratios = payload.cells[rowIndex]?.[columnIndex], centreX = chartLeft + (columnIndex + .5) * columnWidth;
        if (!ratios) { context.fillStyle = '#B5C0C8'; context.textAlign = 'center'; font(context, 14); context.fillText('—', centreX, paneTop + rowHeight / 2 - 7); return; }
        const x = chartLeft + columnIndex * columnWidth + (columnWidth - barWidth) / 2; let running = 0;
        states.forEach((series, seriesIndex) => {
          const ratio = Number(ratios[seriesIndex] || 0), segmentHeight = ratio * rowHeight, y = paneBottom - running - segmentHeight;
          context.fillStyle = series.colour; context.fillRect(x, y, barWidth, segmentHeight);
          if (ratio >= .08) { context.fillStyle = '#FFFFFF'; context.textAlign = 'left'; font(context, 17, true); context.fillText(percent(ratio), x + 3, y + segmentHeight / 2 - 9); }
          else if (ratio >= .005) { context.fillStyle = series.colour; font(context, 12, true); context.fillText(percent(ratio), x + barWidth + 3, Math.max(paneTop, y - 7)); }
          if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: displayKey([...rowKey, ...columnKey]), series: series.name, value: percent(ratio)});
          running += segmentHeight;
        });
      });
    });
    if (rowKeys[0]?.length) {
      const total = Math.max(rowLabelWidths.reduce((sum, value) => sum + value, 0), 1), factor = Math.min((chartLeft - 92) / total, 1); let x = 24;
      rowLabelWidths.forEach((width, level) => {
        const visible = width * factor;
        hierarchySpans(rowKeys, level).forEach(([start, end, value]) => {
          context.fillStyle = '#405765'; context.textAlign = 'left'; font(context, 18, true);
          context.fillText(fittedText(context, value, visible - 8), x + 4, chartTop + (start + end) / 2 * rowHeight - 10);
        });
        x += visible; line(context, x, chartTop, x, chartTop + chartHeight, '#D7DEE3');
      });
    }
    if (!payload.single_column) {
      const captions = columnKeys.map(key => String(key.at(-1) ?? '')); font(context, 16, true);
      const rotate = captions.some(caption => textWidth(context, caption) + 8 > columnWidth);
      captions.forEach((caption, index) => {
        const centre = chartLeft + (index + .5) * columnWidth;
        if (rotate) rotatedLabel(context, caption.slice(0, 24), centre, chartTop + chartHeight + 90, '#4E6271', 16);
        else { context.fillStyle = '#4E6271'; context.textAlign = 'center'; context.fillText(fittedText(context, caption, columnWidth - 8), centre, chartTop + chartHeight + 10); }
      });
    }
    drawLegend(context, payload.legend);
  }

  function drawFailure(context, payload, state, transform) {
    const states = payload.states || [];
    if (payload.mode === 'flat') {
      (payload.rows || []).forEach((row, index) => {
        const y = 120 + index * 42; let x = 390;
        context.fillStyle = '#263B4A'; context.textAlign = 'left'; font(context, 17, true); context.fillText(displayKey(row.key).slice(0, 42), 28, y + 4);
        states.forEach((series, seriesIndex) => {
          const value = Number(row.values?.[seriesIndex] || 0), width = 980 * value / Math.max(payload.maximum, 1);
          if (width) {
            context.fillStyle = series.colour; context.fillRect(x, y, width, 25);
            if (width > 26) { context.fillStyle = '#FFFFFF'; font(context, 16, true); context.fillText(String(value), x + 5, y + 3); }
            pushRectangleHit(state, transform, {x, y, width, height: 25}, {label: displayKey(row.key), series: series.name, value: String(value)});
          }
          x += width;
        });
      });
      drawLegend(context, payload.legend, {fontSize: 13});
      context.fillStyle = '#4E6271'; context.textAlign = 'left'; font(context, 19, true); context.fillText('# of failed / dropped sessions', 390, 820); return;
    }
    const rowKeys = payload.row_keys || [[]], columnKeys = payload.column_keys || [];
    const hasRightLegend = payload.plot_legend_position === 'right' || (payload.legend?.position === 'right' && payload.legend.items?.length);
    const chartLeft = 285, chartTop = 245, chartHeight = 510, chartWidth = hasRightLegend ? 980 : 1250;
    const outerTop = chartTop - 64, rowHeight = chartHeight / rowKeys.length, columnWidth = chartWidth / columnKeys.length;
    const groups = hierarchySpans(columnKeys, 0); font(context, 18, true);
    const rotate = groups.some(([start, end, value]) => textWidth(context, value.slice(0, 20)) + 14 > (end - start) * columnWidth);
    groups.forEach(([start, end, raw]) => {
      const centre = chartLeft + (start + end) / 2 * columnWidth, value = raw.slice(0, 20);
      if (rotate) rotatedLabel(context, value, centre, chartTop - 27, '#566A78', 18);
      else { context.fillStyle = '#566A78'; context.textAlign = 'center'; font(context, 18, true); context.fillText(value, centre, chartTop - 58); }
      line(context, chartLeft + start * columnWidth, chartTop - 24, chartLeft + end * columnWidth, chartTop - 24, '#C8D2D9');
    });
    columnKeys.forEach((key, index) => {
      const lower = (key.slice(1).join(' · ') || key[0] || '').slice(0, 18), centre = chartLeft + (index + .5) * columnWidth;
      context.fillStyle = '#4E6271'; context.textAlign = 'center'; font(context, 15, true); context.fillText(lower, centre, chartTop - 23);
      const cellLeft = chartLeft + index * columnWidth;
      if (index && key[0] === columnKeys[index - 1][0]) dashedVertical(context, cellLeft, chartTop - 24, chartTop + chartHeight + 25);
      else line(context, cellLeft, outerTop, cellLeft, chartTop + chartHeight + 25, '#AEBBC4', 2);
      context.fillStyle = '#566A78'; context.textAlign = 'left'; font(context, 13, true); context.fillText('0', cellLeft + 3, chartTop + chartHeight + 7);
      context.textAlign = 'right'; context.fillText(String(payload.maximum), cellLeft + columnWidth - 3, chartTop + chartHeight + 7);
    });
    const rowLevels = rowKeys[0]?.length || 0, labelWidth = rowLevels ? Math.max((chartLeft - 28) / rowLevels, 65) : 0;
    for (let level = 0; level < rowLevels; level += 1) {
      hierarchySpans(rowKeys, level).forEach(([start, end, value]) => {
        context.fillStyle = '#405765'; context.textAlign = 'left'; font(context, 14, true);
        context.fillText(value.slice(0, 22), 20 + level * labelWidth, chartTop + (start + end) / 2 * rowHeight - 9);
      });
    }
    rowKeys.forEach((rowKey, rowIndex) => {
      const rowTop = chartTop + rowIndex * rowHeight, rowBottom = rowTop + rowHeight, next = rowKeys[rowIndex + 1];
      if (next && rowLevels > 1 && rowKey[0] === next[0]) dashedHorizontal(context, rowBottom, 20, chartLeft + chartWidth);
      else line(context, 20, rowBottom, chartLeft + chartWidth, rowBottom, '#AEBBC4', 2);
      columnKeys.forEach((columnKey, columnIndex) => {
        const values = payload.cells[rowIndex]?.[columnIndex] || [], cellLeft = chartLeft + columnIndex * columnWidth;
        const available = Math.max(columnWidth - 10, 1); let x = cellLeft + 4;
        const barHeight = Math.max(12, Math.min(22, rowHeight * .84)), y = rowTop + (rowHeight - barHeight) / 2, outside = [];
        states.forEach((series, seriesIndex) => {
          const value = Number(values[seriesIndex] || 0), segmentWidth = available * value / Math.max(payload.maximum, 1);
          if (segmentWidth) {
            context.fillStyle = series.colour; context.fillRect(x, y, segmentWidth, barHeight); font(context, 12, true);
            if (segmentWidth >= textWidth(context, String(value)) + 10) { context.fillStyle = '#FFFFFF'; context.textAlign = 'center'; context.textBaseline = 'middle'; context.fillText(String(value), x + segmentWidth / 2, y + barHeight / 2); context.textBaseline = 'top'; }
            else outside.push(String(value));
            pushRectangleHit(state, transform, {x, y, width: segmentWidth, height: barHeight}, {label: displayKey([...rowKey, ...columnKey]), series: series.name, value: String(value)});
          }
          x += segmentWidth;
        });
        if (outside.length) { context.fillStyle = '#34495A'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, 12, true); context.fillText(outside.join(' / '), x + 3, y + 1); }
      });
    });
    line(context, chartLeft + chartWidth, outerTop, chartLeft + chartWidth, chartTop + chartHeight + 25, '#AEBBC4', 2);
    drawLegend(context, payload.legend, {fontSize: 13, sideX: hasRightLegend ? chartLeft + chartWidth + 24 : undefined});
  }

  function drawDistribution(context, payload, state, transform) {
    const keys = payload.keys || [], buckets = payload.buckets || [], left = 125, top = 260, width = 1260, height = 475;
    const barWidth = Math.max(20, Math.min(70, Math.floor(width / Math.max(keys.length * 2, 1))));
    keys.forEach((key, index) => {
      const ratios = payload.cells[index] || [], x = left + index * width / keys.length + 10; let running = 0;
      buckets.forEach((bucket, bucketIndex) => {
        const ratio = Number(ratios[bucketIndex] || 0), segmentHeight = ratio * height, y = top + height - running - segmentHeight;
        context.fillStyle = bucket.colour; context.fillRect(x, y, barWidth, segmentHeight);
        if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: displayKey(key), series: bucket.name, value: percent(ratio)});
        running += segmentHeight;
      });
    });
    drawTopColumnSeparators(context, keys, payload.axis_columns || [], left, width, top, top + height);
    drawHierarchicalAxisLabels(context, keys, left, width, top, top + height); drawLegend(context, payload.legend);
  }

  function cdfGeometry(position) {
    if (position === 'right') return {left: 100, top: 135, width: 1190, height: 590};
    if (position === 'left') return {left: 400, top: 135, width: 1020, height: 590};
    return {left: 100, top: 135, width: 1320, height: 590};
  }

  function drawCdf(context, payload, state, transform) {
    const plot = cdfGeometry(payload.legend?.position), xLow = Number(payload.domain?.x?.[0] ?? 0), xHigh = Number(payload.domain?.x?.[1] ?? 1);
    (payload.series || []).forEach(series => {
      const points = [];
      (series.x || []).forEach((value, index) => {
        const cumulative = Number(series.y?.[index]); if (!finite(value) || !finite(cumulative)) return;
        points.push({x: plot.left + (Number(value) - xLow) / (xHigh - xLow || 1) * plot.width, y: plot.top + plot.height - cumulative * plot.height, value: Number(value), cumulative});
      });
      if (points.length) {
        context.strokeStyle = series.colour; context.lineWidth = Number(series.width || 1); context.beginPath();
        points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y)); context.stroke();
        pushLineHit(state, transform, points, {label: payload.metric, series: series.name || series.legend_name});
      }
    });
    for (let tick = 0; tick <= 100; tick += 25) {
      const y = plot.top + plot.height - tick / 100 * plot.height; line(context, plot.left, y, plot.left + plot.width, y, '#E4E9ED');
      context.fillStyle = '#4E6271'; context.textAlign = 'left'; font(context, 18, true); context.fillText(`${tick}%`, plot.left - 84, y - 10);
    }
    for (let tick = 0; tick <= 5; tick += 1) {
      const value = xLow + (xHigh - xLow) * tick / 5, x = plot.left + plot.width * tick / 5;
      line(context, x, plot.top + plot.height, x, plot.top + plot.height + 7, '#62727E');
      context.fillStyle = '#4E6271'; context.textAlign = 'center'; font(context, 16, true); context.fillText(value.toFixed(1), x, plot.top + plot.height + 7);
    }
    context.fillStyle = '#405765'; context.textAlign = 'center'; font(context, 20, true); context.fillText(String(payload.metric || ''), plot.left + plot.width / 2, plot.top + plot.height + 31);
    drawLegend(context, payload.legend, {fontSize: 11, sideX: payload.legend?.position === 'right' ? 1320 : undefined});
  }

  function drawMultiCdf(context, payload, state, transform) {
    const panels = payload.panels || [], columns = panels.length > 1 ? 2 : 1, rows = Math.max(1, Math.ceil(panels.length / columns));
    const cellWidth = LOGICAL_WIDTH / columns, cellHeight = (LOGICAL_HEIGHT - 80) / rows;
    panels.forEach((panel, index) => {
      const scale = Math.min((cellWidth - 18) / LOGICAL_WIDTH, (cellHeight - 10) / LOGICAL_HEIGHT);
      const width = LOGICAL_WIDTH * scale, height = LOGICAL_HEIGHT * scale;
      const x = index % columns * cellWidth + (cellWidth - width) / 2, y = 80 + Math.floor(index / columns) * cellHeight + (cellHeight - height) / 2;
      context.save(); context.translate(x, y); context.scale(scale, scale); context.fillStyle = '#FFFFFF'; context.fillRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT);
      drawPayload(context, panel, state, {x: transform.x + x * transform.scale, y: transform.y + y * transform.scale, scale: transform.scale * scale}); context.restore();
    });
  }

  function drawMeanBars(context, payload, state, transform) {
    const bars = payload.bars || [], keys = bars.map(bar => bar.key), left = 155, top = 280, width = 1165, baseline = 680;
    const barWidth = Math.min(150, Math.max(30, width / Math.max(bars.length * 1.7, 1)));
    bars.forEach((bar, index) => {
      const height = (baseline - top) * Number(bar.value) / Math.max(Number(payload.maximum), 1), x = left + (index + .5) * width / bars.length - barWidth / 2, y = baseline - height;
      context.fillStyle = bar.colour; context.fillRect(x, y, barWidth, height);
      context.fillStyle = '#263B4A'; context.textAlign = 'left'; font(context, 20, true); context.fillText(Number(bar.value).toFixed(2), x, y - 31);
      pushRectangleHit(state, transform, {x, y, width: barWidth, height}, {label: displayKey(bar.key), series: bar.legend, value: Number(bar.value).toFixed(2)});
    });
    drawTopColumnSeparators(context, keys, payload.axis_columns || [], left, width, top, baseline);
    drawHierarchicalAxisLabels(context, keys, left, width, top, baseline); verticalLabel(context, payload.metric || '', 48, (top + baseline) / 2, '#405765', 21); drawLegend(context, payload.legend);
  }

  function expandedDomain(domain) {
    let low = Number(domain?.[0] ?? 0), high = Number(domain?.[1] ?? 1); if (low === high) high = low + 1; return [low, high];
  }

  function drawScatter(context, payload, state, transform) {
    const left = 130, top = 120, width = 1220, height = 600, xDomain = expandedDomain(payload.domain?.x), yDomain = expandedDomain(payload.domain?.y);
    (payload.series || []).forEach(series => (series.points || []).forEach(point => {
      const x = left + (Number(point[0]) - xDomain[0]) / (xDomain[1] - xDomain[0]) * width, y = top + height - (Number(point[1]) - yDomain[0]) / (yDomain[1] - yDomain[0]) * height;
      context.fillStyle = series.colour; context.beginPath(); context.arc(x, y, 4, 0, Math.PI * 2); context.fill();
      pushPointHit(state, transform, x, y, {label: series.name, series: `${payload.x_label} / ${payload.y_label}`, value: `${numericLabel(point[0])} / ${numericLabel(point[1])}`});
    }));
    for (let tick = 0; tick <= 5; tick += 1) {
      const x = left + width * tick / 5, y = top + height - height * tick / 5;
      const xValue = xDomain[0] + (xDomain[1] - xDomain[0]) * tick / 5, yValue = yDomain[0] + (yDomain[1] - yDomain[0]) * tick / 5;
      line(context, x, top + height, x, top + height + 7, '#62727E'); line(context, left - 7, y, left, y, '#62727E');
      context.fillStyle = '#4E6271'; context.textAlign = 'center'; font(context, 16, true); context.fillText(xValue.toFixed(0), x, top + height + 7);
      context.textAlign = 'right'; context.fillText(yValue.toFixed(1), left - 12, y - 9);
    }
    context.fillStyle = '#405765'; context.textAlign = 'center'; font(context, 20, true); context.fillText(payload.x_label || '', left + width / 2, top + height + 30);
    context.textAlign = 'left'; context.fillText(payload.y_label || '', 40, 90); drawLegend(context, payload.legend, {fontSize: 14});
  }

  function drawMap(context, payload, state, transform) {
    const left = 120, top = 135, width = 1260, height = 610, rawX = expandedDomain(payload.domain?.x), rawY = expandedDomain(payload.domain?.y);
    const xPad = Math.max((rawX[1] - rawX[0]) * .06, .004), yPad = Math.max((rawY[1] - rawY[0]) * .06, .004);
    const xDomain = [rawX[0] - xPad, rawX[1] + xPad], yDomain = [rawY[0] - yPad, rawY[1] + yPad];
    context.fillStyle = '#EDF4F0'; context.fillRect(left, top, width, height);
    for (const fraction of [.2, .4, .6, .8]) { line(context, left + width * fraction, top, left + width * fraction, top + height, '#D8E5DF'); line(context, left, top + height * fraction, left + width, top + height * fraction, '#D8E5DF'); }
    const basemap = payload.basemap, worldBounds = basemap?.world_bounds;
    const tileRecords = mapTileRecords(state.canvas, payload);
    if (Array.isArray(worldBounds) && worldBounds.length === 4) {
      const [worldLeft, worldTop, worldRight, worldBottom] = worldBounds.map(Number);
      const sourceWidth = worldRight - worldLeft, sourceHeight = worldBottom - worldTop;
      if (sourceWidth > 0 && sourceHeight > 0) {
        const tileSize = Number(basemap.tile_size || 256);
        context.save(); context.beginPath(); context.rect(left, top, width, height); context.clip();
        tileRecords.filter(record => record.status === 'ready').forEach(record => {
          const x = left + (record.x * tileSize - worldLeft) / sourceWidth * width;
          const y = top + (record.y * tileSize - worldTop) / sourceHeight * height;
          context.drawImage(record.image, x, y, tileSize / sourceWidth * width + .5, tileSize / sourceHeight * height + .5);
        });
        context.restore();
      }
    }
    context.strokeStyle = '#B9CDC4'; context.lineWidth = 2; context.strokeRect(left, top, width, height);
    (payload.series || []).forEach(series => (series.points || []).forEach(point => {
      let x, y;
      if (Array.isArray(worldBounds) && worldBounds.length === 4) {
        const [worldLeft, worldTop, worldRight, worldBottom] = worldBounds.map(Number);
        const projected = osmWorldCoordinates(point[1], point[0], basemap.zoom);
        x = left + (projected[0] - worldLeft) / (worldRight - worldLeft) * width;
        y = top + (projected[1] - worldTop) / (worldBottom - worldTop) * height;
      } else {
        x = left + (Number(point[0]) - xDomain[0]) / (xDomain[1] - xDomain[0]) * width;
        y = top + height - (Number(point[1]) - yDomain[0]) / (yDomain[1] - yDomain[0]) * height;
      }
      context.fillStyle = series.colour; context.strokeStyle = '#FFFFFF'; context.lineWidth = 1; context.beginPath(); context.arc(x, y, 4, 0, Math.PI * 2); context.fill(); context.stroke();
      pushPointHit(state, transform, x, y, {label: series.name, series: `${payload.y_label} / ${payload.x_label}`, value: `${numericLabel(point[1])} / ${numericLabel(point[0])}`});
    }));
    drawLegend(context, payload.legend, {fontSize: 13});
    context.fillStyle = '#405765'; context.textAlign = 'left'; font(context, 17, true); context.fillText(payload.x_label || '', left, top + height + 16); context.fillText(payload.y_label || '', 26, top - 25);
    if (basemap?.attribution) {
      context.fillStyle = '#FFFFFF'; context.fillRect(left + width - 210, top + height - 25, 206, 21);
      context.fillStyle = '#405765'; font(context, 11); context.fillText(String(basemap.attribution), left + width - 204, top + height - 22);
    }
  }

  function drawTable(context, payload) {
    const headers = payload.headers || [], rows = payload.rows || []; if (!headers.length) return;
    const columnWidth = Math.min(310, Math.floor(1450 / headers.length)), rowHeight = 34, left = 55, top = 115; context.textBaseline = 'top';
    headers.forEach((header, column) => {
      const x = left + column * columnWidth; context.fillStyle = '#23384A'; context.fillRect(x, top, columnWidth, rowHeight);
      context.fillStyle = '#FFFFFF'; context.textAlign = 'left'; font(context, 14, true); context.fillText(String(header).slice(0, 28), x + 8, top + 8);
    });
    rows.forEach((row, rowIndex) => row.forEach((value, column) => {
      const x = left + column * columnWidth, y = top + (rowIndex + 1) * rowHeight;
      context.fillStyle = rowIndex % 2 ? '#FFFFFF' : '#F4F7F9'; context.fillRect(x, y, columnWidth, rowHeight);
      context.strokeStyle = '#D9E1E6'; context.lineWidth = 1; context.strokeRect(x, y, columnWidth, rowHeight);
      context.fillStyle = '#34495A'; context.textAlign = 'left'; font(context, 13); context.fillText(String(value).slice(0, 28), x + 8, y + 8);
    }));
    drawLegend(context, payload.legend);
  }

  function drawPayload(context, payload, state, transform) {
    drawTitle(context, payload?.title || '');
    if (!payload || payload.type === 'empty') {
      context.fillStyle = '#61727D'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, 24);
      context.fillText(payload?.message || 'No chart data available', 50, 440); return;
    }
    if (payload.type === 'status_100') drawStatus(context, payload, state, transform);
    else if (payload.type === 'failure_count') drawFailure(context, payload, state, transform);
    else if (payload.type === 'distribution') drawDistribution(context, payload, state, transform);
    else if (payload.type === 'cdf') drawCdf(context, payload, state, transform);
    else if (payload.type === 'multi_cdf') drawMultiCdf(context, payload, state, transform);
    else if (payload.type === 'mean_bar') drawMeanBars(context, payload, state, transform);
    else if (payload.type === 'scatter') drawScatter(context, payload, state, transform);
    else if (payload.type === 'map') drawMap(context, payload, state, transform);
    else if (payload.type === 'table') drawTable(context, payload);
  }

  function draw(canvas, payload) {
    const context = prepareCanvas(canvas), state = {canvas, hits: []};
    context.fillStyle = '#FFFFFF'; context.fillRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT);
    drawPayload(context, payload, state, {x: 0, y: 0, scale: 1}); renderStates.set(canvas, state);
  }

  function closestHit(hits, x, y) {
    let closest = null, distance = Infinity;
    for (const hit of hits) {
      if (hit.kind === 'rectangle') { if (x >= hit.x && x <= hit.x + hit.width && y >= hit.y && y <= hit.y + hit.height) return {...hit, distance: 0}; continue; }
      if (hit.kind === 'point') { const candidate = Math.hypot(x - hit.x, y - hit.y); if (candidate < distance) { closest = hit; distance = candidate; } continue; }
      if (hit.kind === 'line') {
        for (const point of hit.points) { const candidate = Math.hypot(x - point.x, y - point.y); if (candidate < distance) { closest = {...hit, point}; distance = candidate; } }
      }
    }
    return closest && distance <= 22 ? {...closest, distance} : null;
  }

  function tooltipFor(canvas) {
    let tooltip = canvas.parentElement?.querySelector(':scope > .ds-live-chart-tooltip');
    if (!tooltip && canvas.parentElement) { tooltip = document.createElement('div'); tooltip.className = 'ds-live-chart-tooltip'; tooltip.hidden = true; canvas.parentElement.append(tooltip); }
    return tooltip;
  }

  function attachTooltip(canvas) {
    if (canvas.dataset.tooltipReady) return; canvas.dataset.tooltipReady = 'true';
    canvas.addEventListener('pointermove', event => {
      const view = views.get(canvas), state = renderStates.get(canvas), tooltip = tooltipFor(canvas); if (!view || !state || !tooltip) return;
      if (canvas.classList.contains('is-panning')) { tooltip.hidden = true; return; }
      const bounds = canvas.getBoundingClientRect();
      const x = ((event.clientX - bounds.left) / view.scaleX - view.originX) / view.zoom;
      const y = ((event.clientY - bounds.top) / view.scaleY - view.originY) / view.zoom;
      const hit = closestHit(state.hits, x, y); if (!hit) { tooltip.hidden = true; return; }
      const point = hit.point, lines = [hit.label, hit.series, hit.value || (point ? numericLabel(point.value) : '')].filter(Boolean);
      if (point && finite(point.cumulative)) lines.push(percent(point.cumulative));
      tooltip.replaceChildren(...lines.map((value, index) => { const element = document.createElement(index === 0 ? 'strong' : 'span'); element.textContent = value; return element; }));
      tooltip.hidden = false;
      const parentBounds = canvas.parentElement.getBoundingClientRect(), left = event.clientX - parentBounds.left + 14, top = event.clientY - parentBounds.top + 14;
      tooltip.style.left = `${clamp(left, 8, Math.max(8, parentBounds.width - tooltip.offsetWidth - 8))}px`;
      tooltip.style.top = `${clamp(top, 8, Math.max(8, parentBounds.height - tooltip.offsetHeight - 8))}px`;
    });
    canvas.addEventListener('pointerleave', () => { const tooltip = tooltipFor(canvas); if (tooltip) tooltip.hidden = true; });
  }

  function setChartZoom(canvas, requestedZoom) {
    const camera = cameraFor(canvas);
    camera.zoom = requestedZoom;
    constrainCamera(camera);
    canvas.classList.toggle('ds-chart-zoomed', camera.zoom > 1);
    const payload = models.get(canvas);
    if (payload) draw(canvas, payload);
    canvas.dispatchEvent(new CustomEvent('dashboardchartzoom', {detail: {zoom: camera.zoom}}));
    return camera.zoom;
  }

  function attachPan(canvas) {
    if (canvas.dataset.panReady) return;
    canvas.dataset.panReady = 'true';
    let drag = null, pendingX = 0, pendingY = 0, panFrame = 0;
    const paintPan = () => {
      panFrame = 0;
      const view = views.get(canvas), payload = models.get(canvas);
      if (!view || !payload || (!pendingX && !pendingY)) return;
      const camera = cameraFor(canvas);
      camera.panX += pendingX / view.scaleX;
      camera.panY += pendingY / view.scaleY;
      pendingX = 0; pendingY = 0;
      constrainCamera(camera);
      draw(canvas, payload);
    };
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0 || cameraFor(canvas).zoom <= 1) return;
      drag = {pointerId: event.pointerId, x: event.clientX, y: event.clientY};
      canvas.classList.add('is-panning');
      canvas.setPointerCapture?.(event.pointerId);
      const tooltip = tooltipFor(canvas); if (tooltip) tooltip.hidden = true;
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      pendingX += event.clientX - drag.x; pendingY += event.clientY - drag.y;
      drag.x = event.clientX; drag.y = event.clientY;
      if (!panFrame) panFrame = requestAnimationFrame(paintPan);
      event.preventDefault();
    });
    const stopPan = event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      if (panFrame) { cancelAnimationFrame(panFrame); paintPan(); }
      canvas.releasePointerCapture?.(event.pointerId);
      canvas.classList.remove('is-panning');
      drag = null;
    };
    canvas.addEventListener('pointerup', stopPan);
    canvas.addEventListener('pointercancel', stopPan);
  }

  const resizeObserver = 'ResizeObserver' in globalThis ? new ResizeObserver(entries => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => entries.forEach(entry => { const payload = models.get(entry.target); if (payload) draw(entry.target, payload); }));
  }) : null;

  globalThis.renderDashboardChart = (canvas, payload) => {
    models.set(canvas, payload); draw(canvas, payload); attachTooltip(canvas); attachPan(canvas);
    if (resizeObserver && !observed.has(canvas)) { observed.add(canvas); resizeObserver.observe(canvas); }
  };
  globalThis.setDashboardChartZoom = setChartZoom;
  globalThis.getDashboardChartZoom = canvas => cameraFor(canvas).zoom;
})();
