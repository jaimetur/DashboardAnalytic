import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const require = createRequire(import.meta.url);
const webSocketImplementation = () => globalThis.WebSocket || require('ws');

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const rendererSource = fs.readFileSync(
  path.resolve(moduleDirectory, '../web_interface/static/js/dashboard_charts.js'),
  'utf8',
);

function browserExecutable() {
  const candidates = [
    process.env.DASHBOARD_ANALYTIC_CHROMIUM,
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
  ].filter(Boolean);
  return candidates.find(candidate => fs.existsSync(candidate));
}

function availablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

class DevToolsConnection {
  constructor(url) {
    const WebSocketImplementation = webSocketImplementation();
    this.socket = new WebSocketImplementation(url);
    this.nextId = 1;
    this.pending = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, {once: true});
      this.socket.addEventListener('error', reject, {once: true});
    });
    this.socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const {resolve, reject} = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result || {});
    });
  }

  call(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.socket.send(JSON.stringify({id, method, params}));
    });
  }

  close() {
    this.socket.close();
  }
}

async function startRenderer() {
  const executable = browserExecutable();
  if (!executable) throw new Error('No supported Chromium browser is installed.');
  const port = await availablePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-canvas-renderer-'));
  const browser = spawn(executable, [
    '--headless=new', '--disable-gpu', '--disable-extensions', '--hide-scrollbars',
    '--no-first-run', '--no-default-browser-check', '--no-sandbox',
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio: 'ignore'});

  let version;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) { version = await response.json(); break; }
    } catch (_error) { /* Browser startup is still in progress. */ }
    await delay(50);
  }
  if (!version) {
    browser.kill();
    fs.rmSync(profile, {recursive: true, force: true});
    throw new Error('Chromium did not expose its rendering endpoint.');
  }

  const targetResponse = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'});
  const target = await targetResponse.json();
  const devtools = new DevToolsConnection(target.webSocketDebuggerUrl);
  await devtools.open();
  await devtools.call('Page.enable');
  await devtools.call('Runtime.enable');
  await devtools.call('Emulation.setDeviceMetricsOverride', {
    width: 1600, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  const {frameTree} = await devtools.call('Page.getFrameTree');
  await devtools.call('Page.setDocumentContent', {
    frameId: frameTree.frame.id,
    html: '<!doctype html><html><head><style>html,body{margin:0;width:1600px;height:900px;overflow:hidden}canvas{display:block;width:1600px;height:900px}</style></head><body><canvas id="chart"></canvas></body></html>',
  });
  await devtools.call('Runtime.evaluate', {expression: `${rendererSource}\n//# sourceURL=dashboard_charts.js`});

  const close = () => {
    devtools.close();
    browser.kill();
    fs.rmSync(profile, {recursive: true, force: true});
  };
  return {devtools, close};
}

let renderer;
try {
  renderer = await startRenderer();
} catch (error) {
  process.stdout.write(`${JSON.stringify({ready: false, error: error.message})}\n`);
  process.exit(1);
}
process.stdout.write(`${JSON.stringify({ready: true})}\n`);

const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
for await (const line of lines) {
  if (!line.trim()) continue;
  try {
    const request = JSON.parse(line);
    const expression = `(() => {
      const previous = document.getElementById('chart');
      const canvas = document.createElement('canvas');
      canvas.id = 'chart'; previous.replaceWith(canvas);
      globalThis.renderDashboardChart(canvas, ${JSON.stringify(request.payload)});
      return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
        resolve(globalThis.getDashboardChartHits(canvas));
      })));
    })()`;
    const evaluation = await renderer.devtools.call('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    });
    if (request.payload?.type === 'map') await delay(600);
    const screenshot = await renderer.devtools.call('Page.captureScreenshot', {
      format: 'png', fromSurface: true, captureBeyondViewport: false,
      clip: {x: 0, y: 0, width: 1600, height: 900, scale: 1},
    });
    process.stdout.write(`${JSON.stringify({
      id: request.id,
      png: screenshot.data,
      hits: evaluation.result?.value || [],
    })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({error: error.message})}\n`);
  }
}
renderer.close();
