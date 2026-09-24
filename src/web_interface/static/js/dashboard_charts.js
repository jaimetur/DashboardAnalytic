/* Browser painter for report-faithful E2E Dashboard chart models. */
(() => {
  'use strict';

  const LOGICAL_WIDTH = 1600;
  const LOGICAL_HEIGHT = 900;
  const FONT_FAMILY = 'Arial, sans-serif';
  const AGGREGATION_TITLE_SIZE = 26;
  const LEGEND_TEXT_SIZE = 26;
  const LEGEND_MARKER_SIZE = 30;
  const models = new WeakMap();
  const views = new WeakMap();
  const cameraStates = new WeakMap();
  const nativeFillTexts = new WeakMap();
  const renderStates = new WeakMap();
  const tableDragStates = new WeakMap();
  const observed = new WeakSet();
  const mapTiles = new Map();
  const mapWaits = new WeakMap();
  let resizeFrame = 0;

  const finite = value => Number.isFinite(Number(value));
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const font = (context, size, bold = false) => { context.font = `${bold ? '700 ' : ''}${size}px ${FONT_FAMILY}`; };
  const labelSize = (size, format = {}) => Math.max(9, Math.round(size * ({Small: .82, Medium: 1.08, Large: 1.28}[format.size] || 1)));
  const labelMaximumSize = (width, height, currentSize, format = {}) => {
    if (!format.has_size) return 26;
    // A Large label is the readable target for the available bar area. The
    // other choices remain proportions of that target, rather than fixed
    // point sizes, so the same template remains legible in dense slides.
    const largeTarget = Math.min(34, Math.max(18, Math.round(Math.min(width, height) * .30)));
    const relative = {Small: .72, Medium: .86, Large: 1}[format.size] || .86;
    return Math.max(currentSize, Math.round(largeTarget * relative));
  };
  const labelFont = (context, size, format = {}, fallbackBold = false, applyScale = true) => {
    const weight = format.bold ? '700 ' : (fallbackBold ? '700 ' : '');
    const actualSize = applyScale ? labelSize(size, format) : size;
    context.font = `${format.italic ? 'italic ' : ''}${weight}${actualSize}px ${format.font || FONT_FAMILY}`;
  };
  // Legend Format controls aggregation and legend furniture independently of
  // Label Format. Medium intentionally preserves the historical default;
  // Small and Large are relative choices around that baseline.
  const legendFormatSize = (size, format = {}, level = 0) => {
    const base = size * ({Small: .82, Medium: 1, Large: 1.20}[format.size] || 1);
    return Math.max(10, Math.round(base * ((5 / 6) ** Math.max(0, Number(level) || 0))));
  };
  // Aggregation headers and members must remain legible after a chart is
  // reduced into a multi-chart Dashboard slide.
  const aggregationSize = (format = {}, level = 0) => {
    return legendFormatSize(AGGREGATION_TITLE_SIZE, format, level);
  };
  const aggregationFont = (context, format = {}, level = 0) => {
    const size = aggregationSize(format, level);
    if (format.configured) { labelFont(context, size, format, false, false); return; }
    context.font = `800 ${size}px ${FONT_FAMILY}`;
  };
  const line = (context, x1, y1, x2, y2, colour = '#AEBBC4', width = 1, dash = []) => {
    context.save(); context.strokeStyle = colour; context.lineWidth = width;
    context.setLineDash(Array.isArray(dash) ? dash.map(Number).filter(value => value > 0) : []);
    context.beginPath(); context.moveTo(x1, y1); context.lineTo(x2, y2); context.stroke(); context.restore();
  };
  const textWidth = (context, value) => context.measureText(String(value)).width;
  const drawLabelText = (context, value, x, y, format = {}) => {
    const text = String(value);
    context.fillText(text, x, y);
    if (!format.underline) return;
    const width = textWidth(context, text);
    const left = context.textAlign === 'center' ? x - width / 2 : (context.textAlign === 'right' || context.textAlign === 'end' ? x - width : x);
    const size = Number.parseFloat(context.font) || 12;
    const underlineY = context.textBaseline === 'bottom' ? y + 2 : (context.textBaseline === 'middle' ? y + size / 2 + 2 : y + size + 2);
    context.save(); context.strokeStyle = context.fillStyle; context.lineWidth = Math.max(1, size / 14);
    context.beginPath(); context.moveTo(left, underlineY); context.lineTo(left + width, underlineY); context.stroke(); context.restore();
  };
  const displayKey = key => (key || []).filter(value => value !== '(all)').join(' · ') || '(all)';
  const percent = (value, digits = 1) => `${(Number(value) * 100).toFixed(digits)}%`;
  const tooltipPercent = value => `${(Number(value) * 100).toFixed(2)}%`;
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
    const view = views.get(context.canvas) || {scaleX: 1, scaleY: 1, zoom: 1, originX: 0, originY: 0};
    const zoom = Number(view.zoom) || 1;
    const x = 32 / (Math.max(view.scaleX, .0001) * zoom) - Number(view.originX || 0);
    const y = 20 / (Math.max(view.scaleY, .0001) * zoom) - Number(view.originY || 0);
    context.fillStyle = '#1D3345'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, 40, true);
    context.fillText(String(title || ''), x, y);
  }

  function fittedText(context, value, width) {
    const full = String(value ?? '');
    if (textWidth(context, full) <= width) return full;
    let result = '';
    for (const character of full) { if (textWidth(context, result + character + '…') > width) break; result += character; }
    return `${result.trimEnd()}…`;
  }

  function hierarchyRowLabelSize() {
    return AGGREGATION_TITLE_SIZE;
  }

  function drawFullHierarchyLabel(context, value, x, y, width, size, colour = '#405765', format = {}, level = 0) {
    const label = String(value ?? '');
    context.fillStyle = format.configured && format.color ? format.color : colour; context.textAlign = 'left'; context.textBaseline = 'top'; aggregationFont(context, format, level);
    const measured = textWidth(context, label);
    if (measured <= width) { context.fillText(label, x, y); return; }
    // Preserve the complete aggregation value in its own pane when even the
    // smallest readable font does not fit. Horizontal condensation is only a
    // last resort and avoids silently replacing business labels with an ellipsis.
    context.save(); context.translate(x, y); context.scale(width / measured, 1); context.fillText(label, 0, 0); context.restore();
  }

  function drawFittedAggregationHeader(context, value, centre, y, width, format = {}, level = 0) {
    const label = String(value ?? '');
    const available = Math.max(width - 8, 1);
    let size = aggregationSize(format, level);
    const setFont = () => {
      if (format.configured) labelFont(context, size, format, false, false);
      else context.font = `800 ${size}px ${FONT_FAMILY}`;
    };
    setFont();
    while (size > 11 && textWidth(context, label) > available) { size -= 1; setFont(); }
    const measured = textWidth(context, label);
    if (measured <= available) { context.fillText(label, centre, y); return; }
    context.save(); context.translate(centre, y); context.scale(available / measured, 1); context.fillText(label, 0, 0); context.restore();
  }

  function rotatedLabel(context, value, centreX, bottomY, colour, size, bold = true, angle = 45, format = {}) {
    context.save(); context.translate(centreX, bottomY); context.rotate(-Math.PI * angle / 180);
    context.fillStyle = format.configured && format.color ? format.color : colour; context.textAlign = 'center'; context.textBaseline = 'bottom';
    if (format.configured) labelFont(context, size, format, false, false); else font(context, size, bold);
    context.fillText(String(value), 0, 0); context.restore();
  }

  function verticalLabel(context, value, centreX, centreY, colour, size, bold = true, format = {}) {
    context.save(); context.translate(centreX, centreY); context.rotate(-Math.PI / 2);
    context.fillStyle = colour; context.textAlign = 'center'; context.textBaseline = 'middle'; labelFont(context, size, format, bold);
    context.fillText(String(value), 0, 0); context.restore();
  }

  function expandedBarLabelSize(context, value, width, height, size, maximum = 26, format = {}) {
    labelFont(context, size, format, false, false);
    const labelWidth = textWidth(context, String(value));
    const scale = Math.min((width - 8) / Math.max(labelWidth, 1), (height - 8) / size);
    return scale > 1 ? Math.min(maximum, Math.floor(size * scale)) : size;
  }

  function drawInsideBarLabel(context, value, x, y, width, height, colour, size, format = {}) {
    size = labelSize(size, format); const label = String(value); labelFont(context, size, format, false, false); const labelWidth = textWidth(context, label);
    if (labelWidth + 8 <= width && size + 8 <= height) {
      const fittedSize = expandedBarLabelSize(context, label, width, height, size, labelMaximumSize(width, height, size, format), format); labelFont(context, fittedSize, format, false, false);
      context.fillStyle = colour; context.textAlign = 'center'; context.textBaseline = 'middle'; drawLabelText(context, label, x + width / 2, y + height / 2, format); context.textBaseline = 'top'; return true;
    }
    if (size + 8 <= width && labelWidth + 8 <= height) {
      verticalLabel(context, label, x + width / 2, y + height / 2, colour, size, false, format); return true;
    }
    return false;
  }

  function drawInsideHorizontalBarLabel(context, value, x, y, width, height, colour, size, format = {}) {
    size = labelSize(size, format); const label = String(value); labelFont(context, size, format, false, false); const labelWidth = textWidth(context, label);
    if (labelWidth + 8 > width || size + 8 > height) return false;
    const fittedSize = expandedBarLabelSize(context, label, width, height, size, labelMaximumSize(width, height, size, format), format); labelFont(context, fittedSize, format, false, false);
    context.fillStyle = colour; context.textAlign = 'center'; context.textBaseline = 'middle';
    drawLabelText(context, label, x + width / 2, y + height / 2, format); context.textBaseline = 'top'; return true;
  }

  function stackedChartLabelColour(series, cells) {
    const totals = Array(series.length).fill(0);
    const collect = values => Array.isArray(values) && values.forEach((value, index) => { totals[index] += Number(value) || 0; });
    (cells || []).forEach(cell => Array.isArray(cell?.[0]) ? cell.forEach(collect) : collect(cell));
    const dominant = series[totals.indexOf(Math.max(...totals))]?.colour || '#405765';
    const hex = String(dominant).replace('#', '');
    if (!/^[0-9a-f]{6}$/i.test(hex)) return '#FFFFFF';
    const [red, green, blue] = [0, 2, 4].map(offset => parseInt(hex.slice(offset, offset + 2), 16));
    return (red * 299 + green * 587 + blue * 114) / 1000 > 156 ? '#111111' : '#FFFFFF';
  }

  function drawOutsideBarLabel(context, value, x, y, colour, size = 12, format = {}) {
    const label = String(value);
    context.save();
    labelFont(context, size, format);
    context.textAlign = 'left';
    context.textBaseline = 'top';
    const width = textWidth(context, label);
    context.fillStyle = 'rgba(255, 255, 255, 0.94)';
    context.fillRect(x - 3, y - 2, width + 6, size + 5);
    context.fillStyle = colour;
    drawLabelText(context, label, x, y, format);
    context.restore();
  }

  function drawAdjacentStackLabel(context, value, x, y, width, height, barTop, barBottom, sideSpace, colour, occupied, size = 10, format = {}) {
    context.save(); labelFont(context, size, format);
    const label = String(value), baseWidth = textWidth(context, label);
    size = Math.min(16, Math.max(size, Math.floor(size * (sideSpace - 6) / Math.max(baseWidth, 1))));
    labelFont(context, size, format); const labelWidth = textWidth(context, label);
    const centreY = Math.max(barTop + size / 2, Math.min(barBottom - size / 2, y + height / 2));
    if (labelWidth + 6 > sideSpace || occupied.some(existing => Math.abs(existing - centreY) < size + 3)) { context.restore(); return false; }
    context.fillStyle = colour; context.textAlign = 'left'; context.textBaseline = 'middle';
    drawLabelText(context, label, x + width + 4, centreY, format);
    context.restore(); return true;
  }

  function drawConfiguredBarLabel(context, value, x, y, width, height, colour, size, position, orientation, automatic, format = {}) {
    const placement = String(position || '').toLowerCase();
    if (!placement) { automatic?.(); return; }
    if (placement === 'none') return;
    const horizontal = orientation === 'horizontal';
    const configuredColour = format.color || colour;
    context.save(); labelFont(context, size, format);
    if (placement === 'top') {
      if (horizontal) drawOutsideBarLabel(context, value, x + width + 5, y + Math.max(0, (height - size) / 2), configuredColour, size, format);
      else { context.fillStyle = configuredColour; context.textAlign = 'center'; context.textBaseline = 'bottom'; drawLabelText(context, value, x + width / 2, y - 4, format); }
    } else {
      context.fillStyle = format.color || '#FFFFFF'; context.textBaseline = 'middle';
      if (horizontal) {
        context.textAlign = placement === 'up' ? 'right' : (placement === 'down' ? 'left' : 'center');
        const labelX = placement === 'up' ? x + width - 4 : (placement === 'down' ? x + 4 : x + width / 2);
        drawLabelText(context, value, labelX, y + height / 2, format);
      } else {
        const labelWidth = textWidth(context, value);
        if (labelWidth + 8 > width && size + 8 <= width && labelWidth + 8 <= height) {
          const centreY = placement === 'up'
            ? y + labelWidth / 2 + 4
            : (placement === 'down' ? y + height - labelWidth / 2 - 4 : y + height / 2);
          verticalLabel(context, value, x + width / 2, centreY, format.color || '#FFFFFF', size, false, format);
          context.restore();
          return;
        }
        context.textAlign = 'center';
        const labelY = placement === 'up' ? y + size / 2 + 4 : (placement === 'down' ? y + height - size / 2 - 4 : y + height / 2);
        drawLabelText(context, value, x + width / 2, labelY, format);
      }
    }
    context.restore();
  }

  function drawConfiguredPointLabel(context, value, x, y, colour, position, size = 15, format = {}) {
    const placement = String(position || '').toLowerCase();
    if (!placement || placement === 'none') return;
    const offsets = {
      top: [0, -9, 'center', 'bottom'],
      up: [8, -7, 'left', 'bottom'],
      middle: [9, 0, 'left', 'middle'],
      down: [8, 7, 'left', 'top'],
    };
    const [offsetX, offsetY, align, baseline] = offsets[placement] || offsets.middle;
    context.save(); labelFont(context, size, format); context.textAlign = align; context.textBaseline = baseline;
    const label = String(value ?? ''), labelWidth = textWidth(context, label);
    const labelX = x + offsetX, labelY = y + offsetY;
    context.fillStyle = 'rgba(255, 255, 255, 0.9)';
    const boxX = align === 'center' ? labelX - labelWidth / 2 - 2 : labelX - 2;
    const boxY = baseline === 'bottom' ? labelY - size - 2 : (baseline === 'middle' ? labelY - size / 2 - 2 : labelY - 2);
    context.fillRect(boxX, boxY, labelWidth + 4, size + 4);
    context.fillStyle = format.color || colour; drawLabelText(context, label, labelX, labelY, format); context.restore();
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
    // The x-axis can begin with row aggregation fields. They are still visible
    // header levels in bar charts, so the first hierarchy field is the outer
    // boundary and each child boundary begins below its parent header.
    const outerLevel = 0, headerTop = top - 30 * (keys[0]?.length || 1) - 8;
    for (let index = 1; index < keys.length; index += 1) {
      let changed = keys[index - 1].findIndex((value, level) => String(value) !== String(keys[index][level]));
      if (changed < 0) continue;
      const x = left + index * width / keys.length;
      if (changed === outerLevel) line(context, x, headerTop, x, bottom, '#AEBBC4', 2);
      else dashedVertical(context, x, headerTop + changed * 30, bottom);
    }
  }

  function labelAngle(context, value, availableWidth, size) {
    font(context, size, true); const measured = textWidth(context, value);
    if (measured + 8 <= availableWidth) return 0;
    // A 45° label occupies its text width and height projected onto the
    // column. Use 90° only when that diagonal footprint still overflows.
    return (measured + size) * Math.SQRT1_2 + 8 <= availableWidth ? 45 : 90;
  }

  function bottomAxisReserve(context, keys, width, size = 22) {
    const itemWidth = width / Math.max(keys.length, 1);
    const angles = keys.map(key => labelAngle(context, String(key.at(-1) ?? '').slice(0, 18), itemWidth, size));
    return angles.includes(90) ? 118 : angles.includes(45) ? 90 : 46;
  }

  function drawHierarchicalAxisLabels(context, keys, left, width, top, bottom, format = {}) {
    if (!keys.length) return;
    const levels = keys[0].length, itemWidth = width / keys.length;
    for (let level = 0; level < Math.max(levels - 1, 0); level += 1) {
      for (const [start, end, rawValue] of hierarchySpans(keys, level)) {
        const centre = left + ((start + end) / 2) * itemWidth, value = rawValue.slice(0, 20), y = top - 30 * (levels - level), available = (end - start) * itemWidth;
        const size = aggregationSize(format, level), angle = labelAngle(context, value, available, size);
        if (angle) rotatedLabel(context, value, centre, y + 24, '#566A78', size, true, angle, format);
        else { context.fillStyle = format.configured && format.color ? format.color : '#566A78'; context.textAlign = 'center'; context.textBaseline = 'top'; aggregationFont(context, format, level); context.fillText(value, centre, y); }
        line(context, left + start * itemWidth, y + 24, left + end * itemWidth, y + 24, '#CDD7DE', 1);
      }
    }
    keys.forEach((key, index) => {
      const size = aggregationSize(format), value = String(key.at(-1) ?? '').slice(0, 18), centre = left + (index + .5) * itemWidth, angle = labelAngle(context, value, itemWidth, size);
      if (angle) rotatedLabel(context, value, centre, angle === 45 ? bottom + 82 : bottom + 112, '#62727E', size, true, angle, format);
      else { context.fillStyle = format.configured && format.color ? format.color : '#62727E'; context.textAlign = 'center'; context.textBaseline = 'top'; aggregationFont(context, format); context.fillText(value, centre, bottom + 11); }
    });
  }

  function legendLayout(legend, fontSize = LEGEND_TEXT_SIZE) {
    const items = legend?.items || [];
    let position = items.length ? String(legend?.position || 'none').toLowerCase() : 'none';
    if (!['none', 'top', 'bottom', 'left', 'right'].includes(position)) position = 'top';
    const format = legend?.format || {};
    const size = format.configured ? legendFormatSize(LEGEND_TEXT_SIZE, format) : Math.max(Number(fontSize || LEGEND_TEXT_SIZE), LEGEND_TEXT_SIZE);
    const lineMarkers = Boolean(legend?.line_markers);
    const markerWidth = lineMarkers ? 43 : 32;
    const longestLabel = items.reduce((length, item) => Math.max(length, String(item?.label || '').slice(0, 28).length), 0);
    const estimatedItemWidth = Math.max(120, markerWidth + longestLabel * size * .62 + 24);
    const sideLegendWidth = Math.min(380, Math.max(170, estimatedItemWidth + 20));
    const maximumColumns = lineMarkers ? 6 : 5;
    const columns = ['top', 'bottom'].includes(position)
      ? Math.max(1, Math.min(items.length || 1, maximumColumns, Math.floor(1400 / estimatedItemWidth)))
      : maximumColumns;
    const rows = Math.max(1, Math.ceil(items.length / columns));
    const rowHeight = size + 12;
    return {
      position,
      hasLegend: position !== 'none',
      left: position === 'left' ? sideLegendWidth + 20 : 70,
      right: position === 'right' ? LOGICAL_WIDTH - sideLegendWidth - 20 : 1540,
      top: position === 'top' ? 80 + rows * rowHeight + 18 : 82,
      bottom: position === 'bottom' ? 900 - rows * rowHeight - 22 : 860,
      sideX: position === 'right' ? LOGICAL_WIDTH - sideLegendWidth + 4 : 26,
      size,
      columns,
      rows,
      rowHeight,
    };
  }

  function drawLegend(context, legend, options = {}) {
    const items = legend?.items || [], layout = legendLayout(legend, options.fontSize);
    const {position, size, columns, rowHeight} = layout;
    if (!layout.hasLegend) return;
    const lineMarkers = Boolean(legend.line_markers), markerSize = LEGEND_MARKER_SIZE, format = legend?.format || {};
    const legendLineWidth = width => Math.max(Number(width) > 1 ? Number(width) + 2 : Number(width), 3);
    if (position === 'top' || position === 'bottom') {
      const startY = position === 'top' ? 80 : 900 - layout.rows * rowHeight - 8;
      items.forEach((item, index) => {
        const x = 100 + (index % columns) * (1400 / columns), y = startY + Math.floor(index / columns) * rowHeight;
        const textOnly = !item.colour;
        if (lineMarkers && !textOnly) line(context, x, y + 11, x + 34, y + 11, item.colour, legendLineWidth(item.width), item.dash);
        else if (!textOnly) { context.fillStyle = item.colour; context.fillRect(x, y, markerSize, markerSize); }
        context.fillStyle = format.configured && format.color ? format.color : '#263B4A'; context.textAlign = 'left'; context.textBaseline = 'top'; if (format.configured) labelFont(context, size, format, false, false); else font(context, size, true);
        context.fillText(String(item.label).slice(0, 28), textOnly ? x : x + (lineMarkers ? 43 : 32), y - 1);
      });
      return;
    }
    const x = options.sideX ?? layout.sideX;
    items.forEach((item, index) => {
      const y = 112 + index * (size + 14), textOnly = !item.colour;
      if (lineMarkers && !textOnly) line(context, x, y + 11, x + 34, y + 11, item.colour, legendLineWidth(item.width), item.dash);
      else if (!textOnly) { context.fillStyle = item.colour; context.fillRect(x, y, markerSize, markerSize); }
      context.fillStyle = format.configured && format.color ? format.color : '#263B4A'; context.textAlign = 'left'; context.textBaseline = 'top'; if (format.configured) labelFont(context, size, format, false, false); else font(context, size, true);
      context.fillText(String(item.label).slice(0, 24), textOnly ? x : x + (lineMarkers ? 43 : 32), y - 1);
    });
  }

  function drawStatus(context, payload, state, transform) {
    const states = payload.states || [];
    const stackLabelColour = payload.label_format?.color || stackedChartLabelColour(states, payload.cells);
    if (payload.mode === 'flat') {
      const categories = payload.categories || [], layout = legendLayout(payload.legend, 16);
      const left = layout.left, top = layout.top, width = layout.right - left, height = Math.max(180, layout.bottom - top - 80);
      const yDomain = expandedDomain(payload.domain?.y), ySpan = yDomain[1] - yDomain[0];
      const barWidth = Math.max(24, Math.min(220, Math.floor(width / Math.max(categories.length * 1.25, 1))));
      categories.forEach((category, index) => {
        const ratios = payload.cells[index] || [], x = left + index * width / categories.length + 12; let running = 0;
        const sideLabels = [];
        states.forEach((series, seriesIndex) => {
          const ratio = Number(ratios[seriesIndex] || 0), segmentLow = running, segmentHigh = running + ratio;
          const visibleLow = Math.max(segmentLow, yDomain[0]), visibleHigh = Math.min(segmentHigh, yDomain[1]);
          const segmentHeight = Math.max(0, visibleHigh - visibleLow) / ySpan * height, y = top + (yDomain[1] - visibleHigh) / ySpan * height;
          context.fillStyle = series.colour; context.fillRect(x, y, barWidth, segmentHeight);
          const label = percent(ratio, 2);
          drawConfiguredBarLabel(context, label, x, y, barWidth, segmentHeight, series.colour, 20, payload.label_position, 'vertical', () => {
            if (drawInsideHorizontalBarLabel(context, label, x, y, barWidth, segmentHeight, stackLabelColour, 15, payload.label_format)) return;
            if (ratio > 0) drawAdjacentStackLabel(context, label, x, y, barWidth, segmentHeight, top, top + height, width / categories.length - barWidth - 18, series.colour, sideLabels, 10, payload.label_format);
          }, payload.label_format);
          if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: category, series: series.name, value: tooltipPercent(ratio)});
          running += ratio;
        });
        const label = String(category).slice(0, 24); aggregationFont(context, payload.legend_format);
        if (textWidth(context, label) > width / categories.length - 8) rotatedLabel(context, label, x + barWidth / 2, top + height + 75, '#5A6B78', AGGREGATION_TITLE_SIZE, true, 45, payload.legend_format);
        else { context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#5A6B78'; context.textAlign = 'left'; context.fillText(label, x - 4, top + height + 8); }
      });
      for (let tick = 0; tick <= 5; tick += 1) {
        const value = yDomain[0] + ySpan * tick / 5, y = top + height - tick / 5 * height; line(context, left - 20, y, left + width, y, '#E4E9ED');
        context.fillStyle = '#4E6271'; context.textAlign = 'right'; font(context, 18, true); context.fillText(`${(value * 100).toFixed(0)}%`, left - 14, y - 10);
      }
      drawLegend(context, payload.legend, {fontSize: 16}); return;
    }

    const rowKeys = payload.row_keys || [[]], columnKeys = payload.column_keys || [];
    // Prefer widening the row-hierarchy gutter to horizontally condensing a
    // business label. Dense column layouts still retain a useful plot area.
    const rowLabelSize = aggregationSize(payload.legend_format);
    font(context, rowLabelSize, true);
    const rowLabelWidths = (rowKeys[0] || []).map((_value, level) => Math.max(...rowKeys.map(key => textWidth(context, String(key[level] ?? ''))), 0) + 12);
    const upperLevels = Math.max((columnKeys[0]?.length || 1) - 1, 0), headerBandHeight = Math.min(32, 112 / Math.max(upperLevels, 1));
    const layout = legendLayout(payload.legend), rowOrigin = layout.position === 'left' ? layout.left : 24;
    const chartLeft = Math.max(rowOrigin + 121, Math.min(rowOrigin + 696, rowOrigin + Math.min(rowLabelWidths.reduce((sum, value) => sum + value, 0), 600) + 68));
    const chartTop = layout.top + upperLevels * headerBandHeight + 8, chartRight = layout.right - 10;
    const chartHeight = Math.max(180, layout.bottom - chartTop - 90), chartWidth = chartRight - chartLeft;
    const rowHeight = chartHeight / rowKeys.length, columnWidth = chartWidth / columnKeys.length, barWidth = Math.max(18, Math.min(250, columnWidth * .72));
    const yDomain = expandedDomain(payload.domain?.y), ySpan = yDomain[1] - yDomain[0];
    const headerTop = chartTop - upperLevels * headerBandHeight - 8;
    const rowLabelTotal = Math.max(rowLabelWidths.reduce((sum, value) => sum + value, 0), 1);
    const rowLabelFactor = Math.min((chartLeft - rowOrigin - 68) / rowLabelTotal, 1);
    const nestedRowStart = level => rowOrigin + rowLabelWidths.slice(0, level).reduce((sum, value) => sum + value * rowLabelFactor, 0);
    for (let level = 0; level < upperLevels; level += 1) {
      const bandTop = headerTop + level * headerBandHeight;
      hierarchySpans(columnKeys, level).forEach(([start, end, value]) => {
        const left = chartLeft + start * columnWidth, right = chartLeft + end * columnWidth, caption = fittedText(context, value, right - left - 10);
        context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#405765'; context.textAlign = 'center'; aggregationFont(context, payload.legend_format, level); context.fillText(caption, (left + right) / 2, bandTop + 2);
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
      const changed = next ? rowKey.findIndex((value, level) => value !== next[level]) : 0;
      if (!next || changed === 0) line(context, rowOrigin, paneBottom, chartLeft + chartWidth, paneBottom, '#AEBBC4', 2);
      else dashedHorizontal(context, paneBottom, nestedRowStart(changed), chartLeft + chartWidth);
      (rowIndex === rowKeys.length - 1 ? [0, .5, 1] : [.5, 1]).forEach(fraction => {
        const value = yDomain[0] + ySpan * fraction, y = paneBottom - fraction * rowHeight; line(context, chartLeft, y, chartLeft + chartWidth, y, '#E8ECEF');
        context.fillStyle = '#566A78'; context.textAlign = 'left'; font(context, 15, true); context.fillText(`${(value * 100).toFixed(0)}%`, chartLeft - 50, y - 9);
      });
      columnKeys.forEach((columnKey, columnIndex) => {
        const ratios = payload.cells[rowIndex]?.[columnIndex], centreX = chartLeft + (columnIndex + .5) * columnWidth;
        if (!ratios) { context.fillStyle = '#B5C0C8'; context.textAlign = 'center'; font(context, 14); context.fillText('—', centreX, paneTop + rowHeight / 2 - 7); return; }
        const x = chartLeft + columnIndex * columnWidth + (columnWidth - barWidth) / 2; let running = 0;
        const sideLabels = [];
        states.forEach((series, seriesIndex) => {
          const ratio = Number(ratios[seriesIndex] || 0), segmentLow = running, segmentHigh = running + ratio;
          const visibleLow = Math.max(segmentLow, yDomain[0]), visibleHigh = Math.min(segmentHigh, yDomain[1]);
          const segmentHeight = Math.max(0, visibleHigh - visibleLow) / ySpan * rowHeight, y = paneTop + (yDomain[1] - visibleHigh) / ySpan * rowHeight;
          context.fillStyle = series.colour; context.fillRect(x, y, barWidth, segmentHeight);
          const label = percent(ratio, 2);
          drawConfiguredBarLabel(context, label, x, y, barWidth, segmentHeight, series.colour, 21, payload.label_position, 'vertical', () => {
            if (drawInsideHorizontalBarLabel(context, label, x, y, barWidth, segmentHeight, stackLabelColour, 15, payload.label_format)) return;
            if (ratio > 0) drawAdjacentStackLabel(context, label, x, y, barWidth, segmentHeight, paneTop, paneBottom, (columnWidth - barWidth) / 2 - 6, series.colour, sideLabels, 10, payload.label_format);
          }, payload.label_format);
          if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: displayKey([...rowKey, ...columnKey]), series: series.name, value: tooltipPercent(ratio)});
          running += ratio;
        });
      });
    });
    if (rowKeys[0]?.length) {
      const factor = rowLabelFactor; let x = rowOrigin;
      rowLabelWidths.forEach((width, level) => {
        const visible = width * factor;
        hierarchySpans(rowKeys, level).forEach(([start, end, value]) => {
          drawFullHierarchyLabel(context, value, x + 4, chartTop + (start + end) / 2 * rowHeight - aggregationSize(payload.legend_format, level) / 2, visible - 8, rowLabelSize, '#405765', payload.legend_format, level);
        });
        x += visible; line(context, x, chartTop, x, chartTop + chartHeight, '#D7DEE3');
      });
    }
    if (!payload.single_column) {
      const captions = columnKeys.map(key => String(key.at(-1) ?? '')); aggregationFont(context, payload.legend_format);
      const rotate = captions.some(caption => textWidth(context, caption) + 8 > columnWidth);
      captions.forEach((caption, index) => {
        const centre = chartLeft + (index + .5) * columnWidth;
        if (rotate) rotatedLabel(context, caption.slice(0, 24), centre, chartTop + chartHeight + 90, '#4E6271', AGGREGATION_TITLE_SIZE, true, 45, payload.legend_format);
        else { context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#4E6271'; context.textAlign = 'center'; context.fillText(fittedText(context, caption, columnWidth - 8), centre, chartTop + chartHeight + 10); }
      });
    }
    drawLegend(context, payload.legend);
  }

  function drawFailure(context, payload, state, transform) {
    const states = payload.states || [];
    if (payload.mode === 'flat') {
      const layout = legendLayout(payload.legend, 13), rowOrigin = layout.position === 'left' ? layout.left : 28;
      const barLeft = rowOrigin + 362, maximumBarWidth = Math.max(220, layout.right - barLeft - 20);
      const xDomain = expandedDomain(payload.domain?.x), xSpan = xDomain[1] - xDomain[0];
      (payload.rows || []).forEach((row, index) => {
        const y = layout.top + 28 + index * 42; let running = 0;
        context.fillStyle = '#263B4A'; context.textAlign = 'left'; font(context, 17, true); context.fillText(displayKey(row.key).slice(0, 42), rowOrigin, y + 4);
        states.forEach((series, seriesIndex) => {
          const value = Number(row.values?.[seriesIndex] || 0), segmentLow = running, segmentHigh = running + value;
          const visibleLow = Math.max(segmentLow, xDomain[0]), visibleHigh = Math.min(segmentHigh, xDomain[1]);
          const x = barLeft + (visibleLow - xDomain[0]) / xSpan * maximumBarWidth, width = Math.max(0, visibleHigh - visibleLow) / xSpan * maximumBarWidth;
          if (width) { context.fillStyle = series.colour; context.fillRect(x, y, width, 30); drawConfiguredBarLabel(context, String(value), x, y, width, 30, series.colour, 20, payload.label_position, 'horizontal', () => drawInsideBarLabel(context, String(value), x, y, width, 30, payload.label_format?.color || '#FFFFFF', 20, payload.label_format), payload.label_format); pushRectangleHit(state, transform, {x, y, width, height: 30}, {label: displayKey(row.key), series: series.name, value: String(value)}); }
          running = segmentHigh;
        });
      });
      drawLegend(context, payload.legend, {fontSize: 13}); context.fillStyle = '#4E6271'; context.textAlign = 'left'; font(context, 19, true); context.fillText('# of failed / dropped sessions', barLeft, layout.bottom - 20); return;
    }
    const rowKeys = payload.row_keys || [[]], columnKeys = payload.column_keys || [];
    if (!columnKeys.length) return;
    const upperLevels = Math.max((columnKeys[0]?.length || 1) - 1, 0), headerBandHeight = upperLevels ? Math.min(34, 120 / upperLevels) : 0;
    const layout = legendLayout(payload.legend, 13), rowOrigin = layout.position === 'left' ? layout.left : 20;
    const rowLevels = rowKeys[0]?.length || 0;
    const rowLabelSize = aggregationSize(payload.legend_format);
    font(context, rowLabelSize, true);
    const rowLabelWidths = Array.from({length: rowLevels}, (_value, level) => Math.max(
      ...rowKeys.map(key => textWidth(context, String(key[level] ?? ''))), 0,
    ) + 14);
    const rowLabelGap = rowLevels > 1 ? 20 : 0;
    const rowLabelTotal = Math.max(rowLabelWidths.reduce((sum, value) => sum + value, 0), 1);
    // Keep hierarchy levels in separate panes. The previous fixed 110px
    // gutter caused long parent labels to enter the first chart column.
    const rowLabelArea = rowLevels ? Math.min(440, Math.max(230, rowLabelTotal + rowLabelGap * (rowLevels - 1))) : 0;
    const rowLabelFactor = Math.min((rowLabelArea - rowLabelGap * (rowLevels - 1)) / rowLabelTotal, 1);
    const chartLeft = rowOrigin + rowLabelArea + (rowLevels ? 56 : 110);
    const headerTop = layout.top, baseChartTop = headerTop + upperLevels * headerBandHeight + 8;
    const leafHeaderHeight = Math.max(34, aggregationSize(payload.legend_format) + 8);
    const chartTop = baseChartTop + leafHeaderHeight;
    const chartHeight = Math.max(180, layout.bottom - chartTop - 40), chartWidth = layout.right - chartLeft - 10;
    const xDomain = expandedDomain(payload.domain?.x), xSpan = xDomain[1] - xDomain[0];
    const leafLabelY = baseChartTop - 10, rowHeight = chartHeight / rowKeys.length, columnWidth = chartWidth / columnKeys.length;
    for (let level = 0; level < upperLevels; level += 1) {
      const y = headerTop + level * headerBandHeight;
      hierarchySpans(columnKeys, level).forEach(([start, end, value]) => {
        const centre = chartLeft + (start + end) / 2 * columnWidth;
        context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#566A78'; context.textAlign = 'center'; drawFittedAggregationHeader(context, value, centre, y, (end - start) * columnWidth, payload.legend_format, level);
        line(context, chartLeft + start * columnWidth, y + headerBandHeight - 4, chartLeft + end * columnWidth, y + headerBandHeight - 4, '#C8D2D9');
      });
    }
    columnKeys.forEach((key, index) => {
      const centre = chartLeft + (index + .5) * columnWidth, cellLeft = chartLeft + index * columnWidth;
      context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#4E6271'; context.textAlign = 'center'; drawFittedAggregationHeader(context, key.at(-1), centre, leafLabelY, columnWidth, payload.legend_format);
      if (index) { let changed = columnKeys[index - 1].findIndex((value, level) => value !== key[level]); if (changed < 0) changed = key.length - 1; const lineTop = changed === 0 ? headerTop : headerTop + Math.min(changed, upperLevels) * headerBandHeight; if (changed === 0) line(context, cellLeft, lineTop, cellLeft, chartTop + chartHeight + 25, '#AEBBC4', 2); else dashedVertical(context, cellLeft, lineTop, chartTop + chartHeight + 25); } else line(context, cellLeft, headerTop, cellLeft, chartTop + chartHeight + 25, '#AEBBC4', 2);
      context.fillStyle = '#566A78'; context.textAlign = 'left'; font(context, 13, true); context.fillText(numericLabel(xDomain[0]), cellLeft + 3, chartTop + chartHeight + 7); context.textAlign = 'right'; context.fillText(numericLabel(xDomain[1]), cellLeft + columnWidth - 3, chartTop + chartHeight + 7);
    });
    const nestedRowStart = level => rowOrigin + rowLabelWidths.slice(0, level).reduce((sum, width) => sum + width * rowLabelFactor + rowLabelGap, 0);
    for (let level = 0; level < rowLevels; level += 1) {
      const labelLeft = nestedRowStart(level), labelWidth = rowLabelWidths[level] * rowLabelFactor;
      hierarchySpans(rowKeys, level).forEach(([start, end, value]) => {
        drawFullHierarchyLabel(context, value, labelLeft + 3, chartTop + (start + end) / 2 * rowHeight - aggregationSize(payload.legend_format, level) / 2, labelWidth - 6, rowLabelSize, '#405765', payload.legend_format, level);
      });
      if (level < rowLevels - 1) line(context, labelLeft + labelWidth + rowLabelGap / 2, chartTop, labelLeft + labelWidth + rowLabelGap / 2, chartTop + chartHeight, '#D7DEE3');
    }
    rowKeys.forEach((rowKey, rowIndex) => {
      const rowTop = chartTop + rowIndex * rowHeight, rowBottom = rowTop + rowHeight, next = rowKeys[rowIndex + 1];
      const changed = next ? rowKey.findIndex((value, level) => value !== next[level]) : 0;
      if (next && changed > 0) dashedHorizontal(context, rowBottom, nestedRowStart(changed), chartLeft + chartWidth); else line(context, rowOrigin, rowBottom, chartLeft + chartWidth, rowBottom, '#AEBBC4', 2);
      columnKeys.forEach((columnKey, columnIndex) => {
        const values = payload.cells[rowIndex]?.[columnIndex] || [], cellLeft = chartLeft + columnIndex * columnWidth, available = Math.max(columnWidth - 10, 1); let running = 0, lastSegmentEnd = cellLeft + 4;
        const barHeight = Math.max(16, Math.min(26, rowHeight * .84)), y = rowTop + (rowHeight - barHeight) / 2, outside = [];
        states.forEach((series, seriesIndex) => { const value = Number(values[seriesIndex] || 0), segmentLow = running, segmentHigh = running + value, visibleLow = Math.max(segmentLow, xDomain[0]), visibleHigh = Math.min(segmentHigh, xDomain[1]), x = cellLeft + 4 + (visibleLow - xDomain[0]) / xSpan * available, segmentWidth = Math.max(0, visibleHigh - visibleLow) / xSpan * available; if (segmentWidth) { lastSegmentEnd = Math.max(lastSegmentEnd, x + segmentWidth); context.fillStyle = series.colour; context.fillRect(x, y, segmentWidth, barHeight); drawConfiguredBarLabel(context, String(value), x, y, segmentWidth, barHeight, series.colour, 16, payload.label_position, 'horizontal', () => { if (!drawInsideBarLabel(context, String(value), x, y, segmentWidth, barHeight, payload.label_format?.color || '#FFFFFF', 16, payload.label_format)) outside.push(String(value)); }, payload.label_format); pushRectangleHit(state, transform, {x, y, width: segmentWidth, height: barHeight}, {label: displayKey([...rowKey, ...columnKey]), series: series.name, value: String(value)}); } running = segmentHigh; });
        if (outside.length) { const label = outside.join(' / '), labelX = lastSegmentEnd + 3; context.fillStyle = '#34495A'; context.textAlign = 'left'; context.textBaseline = 'top'; font(context, 16, true); if (labelX + textWidth(context, label) <= cellLeft + columnWidth - 3) context.fillText(label, labelX, y + 1); }
      });
    });
    line(context, chartLeft + chartWidth, headerTop, chartLeft + chartWidth, chartTop + chartHeight + 25, '#AEBBC4', 2); drawLegend(context, payload.legend, {fontSize: 13, sideX: layout.position === 'right' ? chartLeft + chartWidth + 18 : undefined});
  }

  function drawDistribution(context, payload, state, transform) {
    const keys = payload.keys || [], buckets = payload.buckets || [];
    const stackLabelColour = payload.label_format?.color || stackedChartLabelColour(buckets, payload.cells);
    const layout = legendLayout(payload.legend), hierarchyHeight = 30 * (keys[0]?.length || 1) + 8;
    const left = layout.left, top = layout.top + hierarchyHeight, width = layout.right - left;
    const usableBottom = layout.position === 'bottom' ? layout.bottom : 884;
    const height = Math.max(180, usableBottom - top - bottomAxisReserve(context, keys, width));
    const yDomain = expandedDomain(payload.domain?.y), ySpan = yDomain[1] - yDomain[0];
    const barWidth = Math.max(24, Math.min(220, Math.floor(width / Math.max(keys.length * 1.25, 1))));
    for (let tick = 0; tick <= 5; tick += 1) {
      const value = yDomain[0] + ySpan * tick / 5, y = top + height - tick / 5 * height;
      line(context, left, y, left + width, y, '#E4E9ED');
      context.fillStyle = '#4E6271'; context.textAlign = 'right'; font(context, 16, true);
      context.fillText(`${(value * 100).toFixed(0)}%`, left - 12, y - 8);
    }
    line(context, left, top, left, top + height, '#AEBBC4', 2);
    keys.forEach((key, index) => {
      const ratios = payload.cells[index] || [], x = left + index * width / keys.length + 10; let running = 0;
      const sideLabels = [];
      buckets.forEach((bucket, bucketIndex) => {
        const ratio = Number(ratios[bucketIndex] || 0), segmentLow = running, segmentHigh = running + ratio;
        const visibleLow = Math.max(segmentLow, yDomain[0]), visibleHigh = Math.min(segmentHigh, yDomain[1]);
        const segmentHeight = Math.max(0, visibleHigh - visibleLow) / ySpan * height, y = top + (yDomain[1] - visibleHigh) / ySpan * height;
        context.fillStyle = bucket.colour; context.fillRect(x, y, barWidth, segmentHeight);
        const label = percent(ratio, 2); font(context, 17, true);
        const labelWidth = textWidth(context, label);
        drawConfiguredBarLabel(context, label, x, y, barWidth, segmentHeight, bucket.colour, 17, payload.label_position, 'vertical', () => {
          if (drawInsideHorizontalBarLabel(context, label, x, y, barWidth, segmentHeight, stackLabelColour, 14, payload.label_format)) return;
          if (ratio > 0) drawAdjacentStackLabel(context, label, x, y, barWidth, segmentHeight, top, top + height, width / keys.length - barWidth - 16, bucket.colour, sideLabels, 10, payload.label_format);
        }, payload.label_format);
        if (segmentHeight > 0) pushRectangleHit(state, transform, {x, y, width: barWidth, height: segmentHeight}, {label: displayKey(key), series: bucket.name, value: tooltipPercent(ratio)});
        running += ratio;
      });
    });
    drawTopColumnSeparators(context, keys, payload.axis_columns || [], left, width, top, top + height);
    drawHierarchicalAxisLabels(context, keys, left, width, top, top + height, payload.legend_format); drawLegend(context, payload.legend);
  }

  function cdfGeometry(legend) {
    const layout = legendLayout(legend, 11);
    return {left: layout.left, top: layout.top, width: layout.right - layout.left, height: Math.max(180, layout.bottom - layout.top - 42)};
  }

  function drawCdf(context, payload, state, transform) {
    const plot = cdfGeometry(payload.legend), xLow = Number(payload.domain?.x?.[0] ?? 0), xHigh = Number(payload.domain?.x?.[1] ?? 1);
    const yLow = Number(payload.domain?.y?.[0] ?? 0), yHigh = Number(payload.domain?.y?.[1] ?? 1);
    const endpointLabels = [];
    context.save(); context.beginPath(); context.rect(plot.left, plot.top, plot.width, plot.height); context.clip();
    (payload.series || []).forEach(series => {
      const points = [];
      (series.x || []).forEach((value, index) => {
        const cumulative = Number(series.y?.[index]); if (!finite(value) || !finite(cumulative)) return;
        points.push({x: plot.left + (Number(value) - xLow) / (xHigh - xLow || 1) * plot.width, y: plot.top + plot.height - (cumulative - yLow) / (yHigh - yLow || 1) * plot.height, value: Number(value), cumulative});
      });
      if (points.length) {
        context.strokeStyle = series.colour; context.lineWidth = Number(series.width || 1); context.beginPath();
        context.setLineDash(Array.isArray(series.dash) ? series.dash.map(Number).filter(value => value > 0) : []);
        points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y)); context.stroke();
        context.setLineDash([]);
        pushLineHit(state, transform, points, {label: payload.metric, series: series.name || series.legend_name});
        const endpoint = points.at(-1);
        endpointLabels.push({x: endpoint.x, y: endpoint.y, label: series.name || series.legend_name, colour: series.colour});
      }
    });
    context.restore();
    endpointLabels.forEach(item => drawConfiguredPointLabel(
      context, item.label, item.x, item.y, item.colour, payload.label_position, 13, payload.label_format,
    ));
    for (let tick = 0; tick <= 4; tick += 1) {
      const cumulative = yLow + (yHigh - yLow) * tick / 4;
      const y = plot.top + plot.height - tick / 4 * plot.height; line(context, plot.left, y, plot.left + plot.width, y, '#E4E9ED');
      context.fillStyle = '#4E6271'; context.textAlign = 'right'; font(context, 18, true); context.fillText(`${(cumulative * 100).toFixed(0)}%`, plot.left - 14, y - 10);
    }
    for (let tick = 0; tick <= 5; tick += 1) {
      const value = xLow + (xHigh - xLow) * tick / 5, x = plot.left + plot.width * tick / 5;
      line(context, x, plot.top + plot.height, x, plot.top + plot.height + 7, '#62727E');
      context.fillStyle = '#4E6271'; context.textAlign = 'center'; font(context, 16, true); context.fillText(value.toFixed(1), x, plot.top + plot.height + 7);
    }
    context.fillStyle = '#405765'; context.textAlign = 'center'; font(context, 20, true); context.fillText(String(payload.metric || ''), plot.left + plot.width / 2, plot.top + plot.height + 31);
    drawLegend(context, payload.legend, {fontSize: 11, sideX: legendLayout(payload.legend, 11).position === 'right' ? plot.left + plot.width + 25 : undefined});
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
    if (payload.mode === 'hierarchy') {
      const rowKeys = payload.row_keys || [[]], columnKeys = payload.column_keys || [[]];
      const layout = legendLayout(payload.legend), rowOrigin = layout.position === 'left' ? layout.left : 24;
      const rowLevels = rowKeys[0]?.length || 0, labelWidth = rowLevels ? Math.min(140, Math.max(72, (layout.right - rowOrigin) / (rowLevels + 5))) : 0;
      const chartLeft = rowOrigin + rowLevels * labelWidth + 56, chartRight = layout.right - 12;
      const upperLevels = Math.max((columnKeys[0]?.length || 1) - 1, 0), headerHeight = upperLevels * 28;
      const chartTop = layout.top + headerHeight + 8, chartHeight = Math.max(180, layout.bottom - chartTop - 20), chartWidth = chartRight - chartLeft;
      const rowHeight = chartHeight / Math.max(rowKeys.length, 1), columnWidth = chartWidth / Math.max(columnKeys.length, 1);
      const yDomain = expandedDomain(payload.domain?.y), ySpan = yDomain[1] - yDomain[0];
      for (let level = 0; level < upperLevels; level += 1) hierarchySpans(columnKeys, level).forEach(([start, end, value]) => {
        const left = chartLeft + start * columnWidth, right = chartLeft + end * columnWidth;
        context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#405765'; context.textAlign = 'center'; aggregationFont(context, payload.legend_format, level); context.fillText(fittedText(context, value, right - left - 8), (left + right) / 2, layout.top + level * 28);
        line(context, left, layout.top + (level + 1) * 28 - 3, right, layout.top + (level + 1) * 28 - 3, '#C8D2D9');
      });
      for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
        const cellLeft = chartLeft + columnIndex * columnWidth;
        if (!columnIndex) {
          line(context, cellLeft, layout.top, cellLeft, chartTop + chartHeight + 22, '#AEBBC4', 2);
          continue;
        }
        let changed = columnKeys[columnIndex - 1].findIndex((value, level) => value !== columnKeys[columnIndex][level]);
        if (changed < 0) changed = columnKeys[columnIndex].length - 1;
        const lineTop = layout.top + Math.min(changed, upperLevels) * 28;
        if (changed === 0) line(context, cellLeft, lineTop, cellLeft, chartTop + chartHeight + 22, '#AEBBC4', 2);
        else dashedVertical(context, cellLeft, lineTop, chartTop + chartHeight + 22);
      }
      line(context, chartLeft + chartWidth, layout.top, chartLeft + chartWidth, chartTop + chartHeight + 22, '#AEBBC4', 2);
      rowKeys.forEach((rowKey, rowIndex) => {
        const top = chartTop + rowIndex * rowHeight, bottom = top + rowHeight, next = rowKeys[rowIndex + 1];
        const changed = next ? rowKey.findIndex((value, level) => value !== next[level]) : 0;
        if (next && changed > 0) dashedHorizontal(context, bottom, rowOrigin + changed * labelWidth, chartRight); else line(context, rowOrigin, bottom, chartRight, bottom, '#AEBBC4', 2);
        rowKey.forEach((value, level) => { context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#405765'; context.textAlign = 'left'; aggregationFont(context, payload.legend_format, level); context.fillText(fittedText(context, value, labelWidth - 8), rowOrigin + level * labelWidth + 4, top + rowHeight / 2 - 8); });
        columnKeys.forEach((columnKey, columnIndex) => {
          const value = Number(payload.cells?.[rowIndex]?.[columnIndex]); if (!Number.isFinite(value)) return;
          const cellLeft = chartLeft + columnIndex * columnWidth, plotTop = top + 4, plotBottom = bottom - 10, plotHeight = Math.max(1, plotBottom - plotTop);
          const valueY = plotBottom - (value - yDomain[0]) / ySpan * plotHeight, zeroY = plotBottom - (clamp(0, yDomain[0], yDomain[1]) - yDomain[0]) / ySpan * plotHeight;
          const width = Math.max(14, Math.min(columnWidth * .68, 110)), x = cellLeft + (columnWidth - width) / 2, y = Math.max(plotTop, Math.min(valueY, zeroY)), height = Math.max(0, Math.min(plotBottom, Math.max(valueY, zeroY)) - y);
          const colour = payload.cell_colours?.[rowIndex]?.[columnIndex] || '#4E79A7';
          context.fillStyle = colour; context.fillRect(x, y, width, height); const label = value.toFixed(2);
          drawConfiguredBarLabel(context, label, x, y, width, height, colour, 19, payload.label_position, 'vertical', () => { if (!(height >= 36 && drawInsideBarLabel(context, label, x, y, width, height, payload.label_format?.color || '#FFFFFF', 19, payload.label_format))) { context.fillStyle = payload.label_format?.color || colour; context.textAlign = 'center'; labelFont(context, 18, payload.label_format); context.fillText(label, x + width / 2, Math.max(top + 2, y - 22)); } }, payload.label_format);
          pushRectangleHit(state, transform, {x, y, width, height}, {label: displayKey([...rowKey, ...columnKey]), series: payload.aggregation || 'mean', value: label});
          if (rowIndex === rowKeys.length - 1) { context.fillStyle = payload.legend_format?.configured && payload.legend_format.color ? payload.legend_format.color : '#4E6271'; context.textAlign = 'center'; aggregationFont(context, payload.legend_format); context.fillText(fittedText(context, String(columnKey.at(-1) || ''), columnWidth - 8), cellLeft + columnWidth / 2, bottom + 3); }
        });
      });
      drawLegend(context, payload.legend); return;
    }
    const bars = payload.bars || [], keys = bars.map(bar => bar.key);
    const layout = legendLayout(payload.legend), hierarchyHeight = 30 * (keys[0]?.length || 1) + 8;
    const left = Math.max(105, layout.left), top = layout.top + hierarchyHeight;
    const width = layout.right - left, usableBottom = layout.position === 'bottom' ? layout.bottom : 884;
    const baseline = Math.max(top + 180, usableBottom - bottomAxisReserve(context, keys, width));
    const yDomain = expandedDomain(payload.domain?.y), ySpan = yDomain[1] - yDomain[0], plotHeight = baseline - top;
    const zeroY = baseline - (clamp(0, yDomain[0], yDomain[1]) - yDomain[0]) / ySpan * plotHeight;
    const barWidth = Math.min(260, Math.max(32, width / Math.max(bars.length * 1.22, 1)));
    bars.forEach((bar, index) => {
      const valueY = baseline - (Number(bar.value) - yDomain[0]) / ySpan * plotHeight, x = left + (index + .5) * width / bars.length - barWidth / 2;
      const y = Math.max(top, Math.min(valueY, zeroY)), height = Math.max(0, Math.min(baseline, Math.max(valueY, zeroY)) - y);
      context.fillStyle = bar.colour; context.fillRect(x, y, barWidth, height);
      const label = Number(bar.value).toFixed(2);
      drawConfiguredBarLabel(context, label, x, y, barWidth, height, bar.colour, 24, payload.label_position, 'vertical', () => {
        if (height >= 46 && drawInsideBarLabel(context, label, x, y, barWidth, height, payload.label_format?.color || '#FFFFFF', 24, payload.label_format)) {} else {
          context.fillStyle = payload.label_format?.color || bar.colour; context.textAlign = 'center'; labelFont(context, 24, payload.label_format); context.fillText(label, x + barWidth / 2, y - 25);
        }
      }, payload.label_format);
      pushRectangleHit(state, transform, {x, y, width: barWidth, height}, {label: displayKey(bar.key), series: bar.legend, value: Number(bar.value).toFixed(2)});
    });
    drawTopColumnSeparators(context, keys, payload.axis_columns || [], left, width, top, baseline);
    drawHierarchicalAxisLabels(context, keys, left, width, top, baseline, payload.legend_format); verticalLabel(context, payload.metric || '', layout.position === 'left' ? left - 28 : 42, (top + baseline) / 2, '#405765', 21); drawLegend(context, payload.legend, {sideX: layout.position === 'right' ? left + width + 25 : undefined});
  }

  function expandedDomain(domain) {
    let low = Number(domain?.[0] ?? 0), high = Number(domain?.[1] ?? 1); if (low === high) high = low + 1; return [low, high];
  }

  function drawScatter(context, payload, state, transform) {
    const layout = legendLayout(payload.legend, 14), left = layout.left, top = layout.top;
    const width = layout.right - left, height = Math.max(180, layout.bottom - top - 42), xDomain = expandedDomain(payload.domain?.x), yDomain = expandedDomain(payload.domain?.y);
    (payload.series || []).forEach(series => (series.points || []).forEach(point => {
      if (Number(point[0]) < xDomain[0] || Number(point[0]) > xDomain[1] || Number(point[1]) < yDomain[0] || Number(point[1]) > yDomain[1]) return;
      const x = left + (Number(point[0]) - xDomain[0]) / (xDomain[1] - xDomain[0]) * width, y = top + height - (Number(point[1]) - yDomain[0]) / (yDomain[1] - yDomain[0]) * height;
      context.fillStyle = series.colour; context.beginPath(); context.arc(x, y, 4, 0, Math.PI * 2); context.fill();
      drawConfiguredPointLabel(context, series.name, x, y, series.colour, payload.label_position, 13, payload.label_format);
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
    context.textAlign = 'left'; context.fillText(payload.y_label || '', layout.position === 'left' ? left - 28 : 28, top - 5); drawLegend(context, payload.legend, {fontSize: 14, sideX: layout.position === 'right' ? left + width + 25 : undefined});
  }

  function drawMap(context, payload, state, transform) {
    const layout = legendLayout(payload.legend, 13), left = layout.left, top = layout.top;
    const width = layout.right - left, height = Math.max(180, layout.bottom - top - 24), rawX = expandedDomain(payload.domain?.x), rawY = expandedDomain(payload.domain?.y);
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
      if (Number(point[0]) < rawX[0] || Number(point[0]) > rawX[1] || Number(point[1]) < rawY[0] || Number(point[1]) > rawY[1]) return;
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
      drawConfiguredPointLabel(context, series.name, x, y, series.colour, payload.label_position, 13, payload.label_format);
      pushPointHit(state, transform, x, y, {label: series.name, series: `${payload.y_label} / ${payload.x_label}`, value: `${numericLabel(point[1])} / ${numericLabel(point[0])}`});
    }));
    drawLegend(context, payload.legend, {fontSize: 13, sideX: layout.position === 'right' ? left + width + 25 : undefined});
    context.fillStyle = '#405765'; context.textAlign = 'left'; font(context, 17, true); context.fillText(payload.x_label || '', left, top + height + 16); context.fillText(payload.y_label || '', layout.position === 'left' ? left - 28 : 26, top - 25);
    if (basemap?.attribution) {
      context.fillStyle = '#FFFFFF'; context.fillRect(left + width - 210, top + height - 25, 206, 21);
      context.fillStyle = '#405765'; font(context, 11); context.fillText(String(basemap.attribution), left + width - 204, top + height - 22);
    }
  }

  function drawTable(context, payload, state) {
    const headers = payload.headers || [], rows = payload.rows || []; if (!headers.length) return;
    const layout = legendLayout(payload.legend), left = layout.left, top = layout.top;
    const columnWidth = Math.floor((layout.right - left) / Math.max(headers.length, 1)), availableHeight = layout.bottom - top;
    const dynamic = Boolean(payload.dynamic), rowDimensionCount = Math.max(0, Number(payload.row_dimension_count) || 0);
    const columnHeading = String(payload.column_heading || ''), headerBands = dynamic && columnHeading ? 2 : 1;
    const rowHeight = dynamic
      ? Math.max(20, Math.min(38, Math.floor(availableHeight / Math.max(rows.length + headerBands, 1))))
      : Math.max(34, Math.min(58, Math.floor(availableHeight / Math.max(rows.length + 1, 1))));
    const headerTop = top + (headerBands - 1) * rowHeight; context.textBaseline = 'top';
    state.table = dynamic ? {
      left, top, right: layout.right, bottom: layout.bottom, columnWidth, rowHeight,
      headerTop, headerBands, rowDimensionCount, headerCount: headers.length, rowCount: rows.length,
    } : null;
    if (dynamic && columnHeading) {
      const pivotLeft = left + rowDimensionCount * columnWidth;
      context.fillStyle = '#23384A'; context.fillRect(pivotLeft, top, Math.max(columnWidth, layout.right - pivotLeft), rowHeight);
      context.fillStyle = '#FFFFFF'; context.textAlign = 'center'; font(context, 13, true);
      context.fillText(columnHeading.slice(0, 40), pivotLeft + Math.max(columnWidth, layout.right - pivotLeft) / 2, top + 6);
    }
    headers.forEach((header, column) => {
      const x = left + column * columnWidth; context.fillStyle = '#23384A'; context.fillRect(x, headerTop, columnWidth, rowHeight);
      context.fillStyle = '#FFFFFF'; context.textAlign = 'left'; font(context, dynamic ? 12 : 14, true); context.fillText(String(header).slice(0, 28), x + 8, headerTop + (dynamic ? 5 : 8));
    });
    rows.forEach((row, rowIndex) => row.forEach((value, column) => {
      const x = left + column * columnWidth, y = top + (rowIndex + headerBands) * rowHeight;
      const repeatedHierarchyValue = dynamic && column < rowDimensionCount && rowIndex > 0
        && Array.from({length: column + 1}, (_item, index) => String(rows[rowIndex - 1]?.[index] ?? '') === String(row[index] ?? '')).every(Boolean);
      const displayValue = repeatedHierarchyValue ? '' : value;
      context.fillStyle = rowIndex % 2 ? '#FFFFFF' : '#F4F7F9'; context.fillRect(x, y, columnWidth, rowHeight);
      context.strokeStyle = '#D9E1E6'; context.lineWidth = 1; context.strokeRect(x, y, columnWidth, rowHeight);
      context.fillStyle = '#34495A'; context.textAlign = column >= rowDimensionCount && dynamic ? 'right' : 'left'; font(context, dynamic ? 11 : 13, dynamic && column < rowDimensionCount);
      const text = String(displayValue).slice(0, 28); const textX = column >= rowDimensionCount && dynamic ? x + columnWidth - 8 : x + 8;
      context.fillText(text, textX, y + (dynamic ? 4 : 8));
    }));
    if (dynamic) {
      const tableBottom = top + (rows.length + headerBands) * rowHeight;
      const boundaryStyle = (level, levels) => {
        const relativeDepth = level / Math.max(levels - 1, 1);
        if (level === 0) return {colour: '#607887', width: 4};
        if (relativeDepth <= .5) return {colour: '#8296A3', width: 3};
        return {colour: '#A8B7C0', width: 2};
      };
      for (let rowIndex = 1; rowIndex < rows.length; rowIndex += 1) {
        const previous = rows[rowIndex - 1] || [], current = rows[rowIndex] || [];
        const changedLevel = Array.from({length: rowDimensionCount}, (_item, level) => level)
          .find(level => String(previous[level] ?? '') !== String(current[level] ?? ''));
        if (changedLevel === undefined) continue;
        const style = boundaryStyle(changedLevel, rowDimensionCount);
        const y = top + (rowIndex + headerBands) * rowHeight;
        line(context, left + changedLevel * columnWidth, y, layout.right, y, style.colour, style.width);
      }
      const columnKeys = Array.isArray(payload.column_keys) ? payload.column_keys : [];
      const columnLevels = Math.max(1, columnKeys[0]?.length || 0);
      for (let columnIndex = 1; columnIndex < columnKeys.length; columnIndex += 1) {
        const previous = columnKeys[columnIndex - 1] || [], current = columnKeys[columnIndex] || [];
        let changedLevel = previous.findIndex((value, level) => String(value ?? '') !== String(current[level] ?? ''));
        if (changedLevel < 0) changedLevel = columnLevels - 1;
        const style = boundaryStyle(changedLevel, columnLevels);
        const x = left + (rowDimensionCount + columnIndex) * columnWidth;
        const lineTop = changedLevel === 0 ? top : headerTop;
        line(context, x, lineTop, x, tableBottom, style.colour, style.width);
      }
      if (columnKeys.length) {
        const pivotLeft = left + rowDimensionCount * columnWidth;
        line(context, pivotLeft, top, pivotLeft, tableBottom, '#607887', 4);
      }
    }
    const drag = tableDragStates.get(state.canvas);
    if (dynamic && drag?.targetIndex !== undefined) {
      context.save();
      context.strokeStyle = '#7C4DCC'; context.lineWidth = 5;
      if (drag.mode === 'column') {
        const boundary = drag.targetIndex + (drag.after ? 1 : 0);
        const x = left + boundary * columnWidth;
        context.beginPath(); context.moveTo(x, headerTop); context.lineTo(x, top + (rows.length + headerBands) * rowHeight); context.stroke();
      } else {
        const boundary = drag.targetBoundary;
        const y = top + (headerBands + boundary) * rowHeight;
        context.beginPath(); context.moveTo(left, y); context.lineTo(layout.right, y); context.stroke();
      }
      context.restore();
    }
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
    else if (payload.type === 'table') drawTable(context, payload, state);
  }

  function draw(canvas, payload) {
    const context = prepareCanvas(canvas), state = {canvas, hits: []};
    context.fillStyle = '#FFFFFF'; context.fillRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT);
    drawPayload(context, payload, state, {x: 0, y: 0, scale: 1}); renderStates.set(canvas, state);
    const view = views.get(canvas);
    const titleHeight = 40 * Math.min(view?.scaleX || 1, view?.scaleY || 1) * (view?.zoom || 1);
    canvas.dispatchEvent(new CustomEvent('dashboardchartlayout', {detail: {titleTop: 20, titleHeight}}));
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
      if (canvas.classList.contains('is-panning') || canvas.classList.contains('is-selecting')) { tooltip.hidden = true; return; }
      const bounds = canvas.getBoundingClientRect();
      const x = ((event.clientX - bounds.left) / view.scaleX - view.originX) / view.zoom;
      const y = ((event.clientY - bounds.top) / view.scaleY - view.originY) / view.zoom;
      const hit = closestHit(state.hits, x, y); if (!hit) { tooltip.hidden = true; return; }
      const point = hit.point, lines = [hit.label, hit.series, hit.value || (point ? numericLabel(point.value) : '')].filter(Boolean);
      if (point && finite(point.cumulative)) lines.push(tooltipPercent(point.cumulative));
      tooltip.replaceChildren(...lines.map((value, index) => { const element = document.createElement(index === 0 ? 'strong' : 'span'); element.textContent = value; return element; }));
      tooltip.hidden = false;
      const parentBounds = canvas.parentElement.getBoundingClientRect(), left = event.clientX - parentBounds.left + 14, top = event.clientY - parentBounds.top + 14;
      tooltip.style.left = `${clamp(left, 8, Math.max(8, parentBounds.width - tooltip.offsetWidth - 8))}px`;
      tooltip.style.top = `${clamp(top, 8, Math.max(8, parentBounds.height - tooltip.offsetHeight - 8))}px`;
    });
    canvas.addEventListener('pointerleave', () => { const tooltip = tooltipFor(canvas); if (tooltip) tooltip.hidden = true; });
  }

  function tableLogicalPoint(canvas, event) {
    const view = views.get(canvas), bounds = canvas.getBoundingClientRect();
    if (!view) return null;
    return {
      x: ((event.clientX - bounds.left) / view.scaleX - view.originX) / view.zoom,
      y: ((event.clientY - bounds.top) / view.scaleY - view.originY) / view.zoom,
    };
  }

  function tableCellAt(canvas, event) {
    const state = renderStates.get(canvas), table = state?.table, point = tableLogicalPoint(canvas, event);
    if (!table || !point || point.x < table.left || point.x >= table.right) return null;
    const column = Math.max(0, Math.min(table.headerCount - 1, Math.floor((point.x - table.left) / table.columnWidth)));
    if (point.y >= table.headerTop && point.y < table.headerTop + table.rowHeight) return {kind: 'header', column, point, table};
    const bodyTop = table.top + table.headerBands * table.rowHeight;
    if (point.y < bodyTop || point.y >= bodyTop + table.rowCount * table.rowHeight) return null;
    return {
      kind: 'row', column,
      row: Math.max(0, Math.min(table.rowCount - 1, Math.floor((point.y - bodyTop) / table.rowHeight))),
      point, table,
    };
  }

  function hierarchyRange(rows, rowIndex, depth) {
    const prefix = rows[rowIndex].slice(0, depth + 1).map(String);
    const matches = row => prefix.every((value, index) => String(row[index]) === value);
    let start = rowIndex, end = rowIndex + 1;
    while (start > 0 && matches(rows[start - 1])) start -= 1;
    while (end < rows.length && matches(rows[end])) end += 1;
    return {start, end};
  }

  function moveArrayItem(values, from, to) {
    const [item] = values.splice(from, 1);
    values.splice(to > from ? to - 1 : to, 0, item);
  }

  function sameImmediateHierarchyParent(left, right) {
    const leftKey = Array.isArray(left) ? left.map(String) : [];
    const rightKey = Array.isArray(right) ? right.map(String) : [];
    const parentDepth = Math.max(0, Math.min(leftKey.length, rightKey.length) - 1);
    return Array.from({length: parentDepth}, (_item, index) => leftKey[index] === rightKey[index]).every(Boolean);
  }

  function attachTableReordering(canvas) {
    if (canvas.dataset.tableReorderReady) return;
    canvas.dataset.tableReorderReady = 'true';
    let drag = null;
    const stopEvent = event => { event.preventDefault(); event.stopImmediatePropagation(); };
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0 || cameraFor(canvas).zoom !== 1) return;
      const payload = models.get(canvas), cell = tableCellAt(canvas, event);
      if (!payload?.dynamic || !cell) return;
      if (cell.kind === 'header' && cell.column >= cell.table.rowDimensionCount) {
        const sourceKeyIndex = cell.column - cell.table.rowDimensionCount;
        drag = {
          mode: 'column', pointerId: event.pointerId, sourceIndex: cell.column,
          sourceKeyIndex, sourceKey: payload.column_keys?.[sourceKeyIndex] || [],
          targetIndex: cell.column, after: false,
        };
      } else if (cell.kind === 'row') {
        const depth = Math.min(cell.column, Math.max(0, cell.table.rowDimensionCount - 1));
        const source = hierarchyRange(payload.rows, cell.row, depth);
        const parent = depth > 0 ? hierarchyRange(payload.rows, cell.row, depth - 1) : {start: 0, end: payload.rows.length};
        drag = {mode: 'row', pointerId: event.pointerId, depth, source, parent, targetIndex: cell.row, targetBoundary: source.start};
      } else return;
      tableDragStates.set(canvas, drag);
      canvas.classList.add('is-table-reordering');
      canvas.style.cursor = 'grabbing';
      canvas.setPointerCapture?.(event.pointerId);
      const tooltip = tooltipFor(canvas); if (tooltip) tooltip.hidden = true;
      stopEvent(event);
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag) {
        const payload = models.get(canvas), cell = tableCellAt(canvas, event);
        const draggable = payload?.dynamic && cell && (cell.kind === 'row' || cell.column >= cell.table.rowDimensionCount);
        canvas.style.cursor = draggable ? 'grab' : '';
        return;
      }
      if (event.pointerId !== drag.pointerId) return;
      const payload = models.get(canvas), cell = tableCellAt(canvas, event);
      if (!payload?.dynamic || !cell) { stopEvent(event); return; }
      if (drag.mode === 'column' && cell.kind === 'header' && cell.column >= cell.table.rowDimensionCount) {
        const targetKey = payload.column_keys?.[cell.column - cell.table.rowDimensionCount] || [];
        if (sameImmediateHierarchyParent(drag.sourceKey, targetKey)) {
          drag.targetIndex = cell.column;
          const cellLeft = cell.table.left + cell.column * cell.table.columnWidth;
          drag.after = cell.point.x >= cellLeft + cell.table.columnWidth / 2;
        }
      } else if (drag.mode === 'row' && cell.kind === 'row') {
        if (cell.row >= drag.parent.start && cell.row < drag.parent.end) {
          drag.targetIndex = cell.row;
          const target = hierarchyRange(payload.rows, cell.row, drag.depth);
          const bodyTop = cell.table.top + cell.table.headerBands * cell.table.rowHeight;
          const after = cell.point.y >= bodyTop + cell.row * cell.table.rowHeight + cell.table.rowHeight / 2;
          drag.targetBoundary = after ? Math.min(target.end, drag.parent.end) : Math.max(target.start, drag.parent.start);
        }
      }
      draw(canvas, payload);
      stopEvent(event);
    });
    const finish = event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const payload = models.get(canvas), completed = drag;
      drag = null;
      tableDragStates.delete(canvas);
      canvas.releasePointerCapture?.(event.pointerId);
      canvas.classList.remove('is-table-reordering');
      canvas.style.cursor = '';
      if (event.type === 'pointerup' && payload?.dynamic) {
        if (completed.mode === 'column') {
          const destination = completed.targetIndex + (completed.after ? 1 : 0);
          if (destination !== completed.sourceIndex && destination !== completed.sourceIndex + 1) {
            moveArrayItem(payload.headers, completed.sourceIndex, destination);
            payload.rows.forEach(row => moveArrayItem(row, completed.sourceIndex, destination));
            if (Array.isArray(payload.column_keys) && payload.column_keys.length) {
              moveArrayItem(payload.column_keys, completed.sourceKeyIndex, destination - completed.sourceIndex + completed.sourceKeyIndex);
            }
          }
        } else {
          const insideSource = completed.targetBoundary >= completed.source.start
            && completed.targetBoundary <= completed.source.end;
          if (!insideSource) {
            const moved = payload.rows.splice(completed.source.start, completed.source.end - completed.source.start);
            let destination = completed.targetBoundary;
            if (destination > completed.source.start) destination -= moved.length;
            payload.rows.splice(Math.max(0, destination), 0, ...moved);
          }
        }
        canvas.dispatchEvent(new CustomEvent('dashboardtableorderchange', {detail: {
          headers: [...payload.headers], rows: payload.rows.map(row => [...row]),
        }}));
      }
      draw(canvas, payload);
      stopEvent(event);
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', finish);
    canvas.addEventListener('pointerleave', () => { if (!drag) canvas.style.cursor = ''; });
  }

  function setChartZoom(canvas, requestedZoom) {
    const camera = cameraFor(canvas);
    camera.zoom = requestedZoom;
    constrainCamera(camera);
    canvas.classList.toggle('ds-chart-zoomed', camera.zoom > 1);
    if (camera.zoom > 1) canvas.classList.remove('ds-chart-selection-blocked');
    const payload = models.get(canvas);
    if (payload) draw(canvas, payload);
    canvas.dispatchEvent(new CustomEvent('dashboardchartzoom', {detail: {zoom: camera.zoom}}));
    return camera.zoom;
  }

  function chartPanState(canvas) {
    const camera = constrainCamera(cameraFor(canvas));
    const maximumX = LOGICAL_WIDTH * (camera.zoom - 1) / 2;
    const maximumY = LOGICAL_HEIGHT * (camera.zoom - 1) / 2;
    return {
      zoom: camera.zoom,
      canPanLeft: camera.zoom > 1 && camera.panX < maximumX - 0.5,
      canPanRight: camera.zoom > 1 && camera.panX > -maximumX + 0.5,
      canPanUp: camera.zoom > 1 && camera.panY < maximumY - 0.5,
      canPanDown: camera.zoom > 1 && camera.panY > -maximumY + 0.5,
    };
  }

  function panChart(canvas, direction) {
    const camera = cameraFor(canvas);
    if (camera.zoom <= 1 || !['left', 'right', 'up', 'down'].includes(direction)) return chartPanState(canvas);
    if (direction === 'left') camera.panX += LOGICAL_WIDTH * 0.16;
    if (direction === 'right') camera.panX -= LOGICAL_WIDTH * 0.16;
    if (direction === 'up') camera.panY += LOGICAL_HEIGHT * 0.16;
    if (direction === 'down') camera.panY -= LOGICAL_HEIGHT * 0.16;
    constrainCamera(camera);
    const payload = models.get(canvas);
    if (payload) draw(canvas, payload);
    const state = chartPanState(canvas);
    canvas.dispatchEvent(new CustomEvent('dashboardchartpan', {detail: state}));
    return state;
  }

  function selectionOverlayFor(canvas) {
    let overlay = canvas.parentElement?.querySelector(':scope > .ds-chart-zoom-selection');
    if (!overlay && canvas.parentElement) {
      overlay = document.createElement('div');
      overlay.className = 'ds-chart-zoom-selection';
      overlay.hidden = true;
      canvas.parentElement.append(overlay);
    }
    return overlay;
  }

  function zoomToSelection(canvas, selection) {
    const bounds = canvas.getBoundingClientRect();
    const left = clamp(Math.min(selection.startX, selection.endX) - bounds.left, 0, bounds.width);
    const top = clamp(Math.min(selection.startY, selection.endY) - bounds.top, 0, bounds.height);
    const right = clamp(Math.max(selection.startX, selection.endX) - bounds.left, 0, bounds.width);
    const bottom = clamp(Math.max(selection.startY, selection.endY) - bounds.top, 0, bounds.height);
    const width = right - left;
    const height = bottom - top;
    if (width < 12 || height < 12) return;
    const selectedWidth = width / bounds.width * LOGICAL_WIDTH;
    const selectedHeight = height / bounds.height * LOGICAL_HEIGHT;
    const zoom = Math.min(4, LOGICAL_WIDTH / selectedWidth, LOGICAL_HEIGHT / selectedHeight);
    if (zoom <= 1) return;
    const centreX = (left + width / 2) / bounds.width * LOGICAL_WIDTH;
    const centreY = (top + height / 2) / bounds.height * LOGICAL_HEIGHT;
    const camera = cameraFor(canvas);
    camera.zoom = zoom;
    camera.panX = zoom * (LOGICAL_WIDTH / 2 - centreX);
    camera.panY = zoom * (LOGICAL_HEIGHT / 2 - centreY);
    constrainCamera(camera);
    canvas.classList.toggle('ds-chart-zoomed', camera.zoom > 1);
    if (camera.zoom > 1) canvas.classList.remove('ds-chart-selection-blocked');
    const payload = models.get(canvas);
    if (payload) draw(canvas, payload);
    canvas.dispatchEvent(new CustomEvent('dashboardchartzoom', {detail: {zoom: camera.zoom}}));
  }

  function selectionStartAllowed(canvas, event) {
    const view = views.get(canvas);
    const bounds = canvas.getBoundingClientRect();
    if (!view || !bounds.height) return false;
    const logicalY = (event.clientY - bounds.top) / view.scaleY;
    // The chart title occupies the top band. Selection zoom starts only in
    // the plot and data-label area, never under titles or floating controls.
    return logicalY >= 90;
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
      canvas.dispatchEvent(new CustomEvent('dashboardchartpan', {detail: chartPanState(canvas)}));
    };
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const selecting = cameraFor(canvas).zoom <= 1 && event.pointerType === 'mouse' && selectionStartAllowed(canvas, event);
      if (!selecting && cameraFor(canvas).zoom <= 1) return;
      drag = {pointerId: event.pointerId, x: event.clientX, y: event.clientY, selecting, startX: event.clientX, startY: event.clientY};
      canvas.classList.add(selecting ? 'is-selecting' : 'is-panning');
      canvas.setPointerCapture?.(event.pointerId);
      const tooltip = tooltipFor(canvas); if (tooltip) tooltip.hidden = true;
      if (!selecting) event.preventDefault();
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag && cameraFor(canvas).zoom <= 1) {
        canvas.classList.toggle('ds-chart-selection-blocked', !selectionStartAllowed(canvas, event));
      }
      if (!drag || event.pointerId !== drag.pointerId) return;
      if (drag.selecting) {
        drag.endX = event.clientX; drag.endY = event.clientY;
        const bounds = canvas.getBoundingClientRect(), parentBounds = canvas.parentElement.getBoundingClientRect();
        const overlay = selectionOverlayFor(canvas);
        if (overlay) {
          const left = clamp(Math.min(drag.startX, drag.endX), bounds.left, bounds.right);
          const top = clamp(Math.min(drag.startY, drag.endY), bounds.top, bounds.bottom);
          const right = clamp(Math.max(drag.startX, drag.endX), bounds.left, bounds.right);
          const bottom = clamp(Math.max(drag.startY, drag.endY), bounds.top, bounds.bottom);
          overlay.style.left = `${left - parentBounds.left}px`; overlay.style.top = `${top - parentBounds.top}px`;
          overlay.style.width = `${right - left}px`; overlay.style.height = `${bottom - top}px`; overlay.hidden = false;
        }
        event.preventDefault();
        return;
      }
      pendingX += event.clientX - drag.x; pendingY += event.clientY - drag.y;
      drag.x = event.clientX; drag.y = event.clientY;
      if (!panFrame) panFrame = requestAnimationFrame(paintPan);
      event.preventDefault();
    });
    const stopPan = event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const completedDrag = drag;
      if (completedDrag.selecting) {
        completedDrag.endX ??= event.clientX; completedDrag.endY ??= event.clientY;
        const overlay = selectionOverlayFor(canvas); if (overlay) overlay.hidden = true;
        if (event.type === 'pointerup') zoomToSelection(canvas, completedDrag);
      } else if (panFrame) { cancelAnimationFrame(panFrame); paintPan(); }
      canvas.releasePointerCapture?.(event.pointerId);
      canvas.classList.remove('is-panning', 'is-selecting');
      drag = null;
      if (cameraFor(canvas).zoom <= 1) canvas.classList.toggle('ds-chart-selection-blocked', !selectionStartAllowed(canvas, event));
    };
    canvas.addEventListener('pointerup', stopPan);
    canvas.addEventListener('pointercancel', stopPan);
  }

  const resizeObserver = 'ResizeObserver' in globalThis ? new ResizeObserver(entries => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => entries.forEach(entry => { const payload = models.get(entry.target); if (payload) draw(entry.target, payload); }));
  }) : null;

  globalThis.renderDashboardChart = (canvas, payload) => {
    models.set(canvas, payload); draw(canvas, payload); attachTooltip(canvas); attachTableReordering(canvas); attachPan(canvas);
    if (resizeObserver && !observed.has(canvas)) { observed.add(canvas); resizeObserver.observe(canvas); }
  };
  globalThis.getDashboardChartHits = canvas => structuredClone(renderStates.get(canvas)?.hits || []);
  globalThis.setDashboardChartZoom = setChartZoom;
  globalThis.getDashboardChartZoom = canvas => cameraFor(canvas).zoom;
  globalThis.panDashboardChart = panChart;
  globalThis.getDashboardChartPanState = chartPanState;
})();
