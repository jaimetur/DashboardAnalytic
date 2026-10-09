/* Background dataset uploads that survive leaving the page.
 *
 * The files chosen in Workspace and their classification are kept in the browser (IndexedDB) until
 * the upload ends, and every file is sent in chunks to the upload session of the workspace the upload
 * started in. Each page of the application resumes the pending uploads of the signed-in user from the
 * bytes the server already has, so changing page, module or workspace never interrupts them. The
 * progress is shown in the floating background task cards.
 */
(() => {
  'use strict';

  const config = (() => {
    try { return JSON.parse(document.getElementById('background-uploads-config')?.textContent || '{}') || {}; } catch (_error) { return {}; }
  })();
  if (!config.username) return;

  const DATABASE = 'drivetest-analyzer-uploads';
  const STORE = 'uploads';
  const CHUNK_BYTES = 8 * 1024 * 1024;
  const RETRY_DELAYS_MS = [1000, 3000, 8000, 15000];
  const running = new Map();
  const memoryRecords = new Map();

  const openDatabase = () => new Promise((resolve) => {
    if (!('indexedDB' in window)) { resolve(null); return; }
    let request;
    try { request = indexedDB.open(DATABASE, 1); } catch (_error) { resolve(null); return; }
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, {keyPath: 'key'});
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
  });
  const withStore = async (mode, action) => {
    const database = await openDatabase();
    if (!database) return null;
    return new Promise((resolve) => {
      try {
        const transaction = database.transaction(STORE, mode);
        const result = action(transaction.objectStore(STORE));
        transaction.oncomplete = () => { database.close(); resolve(result?.result ?? true); };
        transaction.onerror = transaction.onabort = () => { database.close(); resolve(null); };
      } catch (_error) {
        database.close();
        resolve(null);
      }
    });
  };
  // Without IndexedDB (a private window) the upload still goes on while the page stays open.
  const saveRecord = async (record) => {
    memoryRecords.set(record.key, record);
    return withStore('readwrite', (store) => store.put(record));
  };
  const removeRecord = async (record) => {
    memoryRecords.delete(record.key);
    return withStore('readwrite', (store) => store.delete(record.key));
  };
  const listRecords = async () => {
    const stored = await withStore('readonly', (store) => store.getAll());
    const records = new Map((Array.isArray(stored) ? stored : []).map((record) => [record.key, record]));
    memoryRecords.forEach((record, key) => { if (!records.has(key)) records.set(key, record); });
    return [...records.values()].filter((record) => record.username === config.username);
  };

  const publish = (record, detail) => window.dispatchEvent(new CustomEvent('drivetest-analyzer:background-task', {detail: {
    id: `dataset-upload:${record.upload_id}`,
    workspace_id: record.workspace_id,
    workspace_name: record.workspace_name,
    is_active: record.workspace_id === config.workspace_id,
    label: `Uploading ${record.names.length} dataset${record.names.length === 1 ? '' : 's'}`,
    started_at: record.started_at,
    cancel: () => cancel(record),
    ...detail,
  }}));

  const request = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const payload = await response.json().catch(() => ({}));
    return {response, payload};
  };
  const sessionUrl = (record) => `/api/uploads/${encodeURIComponent(record.workspace_id)}/${encodeURIComponent(record.upload_id)}`;
  const wait = (milliseconds) => new Promise((resolve) => { window.setTimeout(resolve, milliseconds); });

  async function cancel(record) {
    running.get(record.key)?.abort();
    await request(sessionUrl(record), {method: 'DELETE'}).catch(() => null);
    await removeRecord(record);
    publish(record, {status: 'cancelled'});
  }

  async function send(record, controller) {
    const {response, payload} = await request(sessionUrl(record), {signal: controller.signal});
    if (response.status === 404 || response.status === 403) {
      // Cancelled elsewhere, or the workspace was removed.
      await removeRecord(record);
      publish(record, {status: 'cancelled'});
      return;
    }
    if (!response.ok) throw new Error(payload.detail || 'The upload could not be resumed.');
    const sizes = record.files.map((file) => file.size);
    const total = sizes.reduce((sum, size) => sum + size, 0) || 1;
    const received = [...payload.received];
    const progress = () => Math.min(99, received.reduce((sum, value) => sum + value, 0) * 100 / total);
    for (let index = 0; index < record.files.length; index += 1) {
      while (received[index] < sizes[index]) {
        const offset = received[index];
        const chunk = record.files[index].slice(offset, offset + CHUNK_BYTES);
        const sent = await request(`${sessionUrl(record)}/files/${index}?offset=${offset}`, {
          method: 'PUT', body: chunk, signal: controller.signal, headers: {'Content-Type': 'application/octet-stream'},
        });
        if (!sent.response.ok && sent.response.status !== 409) throw new Error(sent.payload.detail || 'A chunk could not be sent.');
        received[index] = Number(sent.payload.received ?? offset);
        publish(record, {
          status: 'processing', progress: progress(),
          detail: `Uploading ${record.names[index]} (${index + 1} of ${record.files.length})`,
          duration_seconds: Math.max(0, Date.now() / 1000 - record.started_at),
        });
      }
    }
    publish(record, {status: 'processing', progress: 99, detail: 'Queuing the processing'});
    const done = await request(`${sessionUrl(record)}/complete`, {method: 'POST', signal: controller.signal});
    if (!done.response.ok) throw new Error(done.payload.detail || 'The datasets could not be registered.');
    await removeRecord(record);
    publish(record, {status: 'completed', detail: `Upload completed: processing in ${record.workspace_name}`, progress: 100});
    window.dispatchEvent(new CustomEvent('drivetest-analyzer:upload-completed', {detail: {...done.payload, upload_id: record.upload_id}}));
    // Still on the Workspace page of the upload's workspace: show the new datasets, as before.
    if (record.workspace_id === config.workspace_id && window.location.pathname === '/workspace' && done.payload.redirect_url) {
      window.location.assign(done.payload.redirect_url);
    }
  }

  async function run(record) {
    if (running.has(record.key)) return;
    const work = async () => {
      const controller = new AbortController();
      running.set(record.key, controller);
      try {
        for (let attempt = 0; ; attempt += 1) {
          try {
            await send(record, controller);
            return;
          } catch (error) {
            if (controller.signal.aborted) return;
            if (attempt >= RETRY_DELAYS_MS.length) {
              // Kept for the next page: the upload resumes from the bytes the server has.
              publish(record, {status: 'processing', detail: `Paused: ${error.message} It resumes when a page is opened again.`,
                progress: 0});
              return;
            }
            publish(record, {status: 'processing', detail: 'Connection lost, retrying…'});
            await wait(RETRY_DELAYS_MS[attempt]);
          }
        }
      } finally {
        running.delete(record.key);
      }
    };
    // One browser tab sends each upload; the others leave it alone.
    if (navigator.locks?.request) {
      navigator.locks.request(`drivetest-analyzer-upload-${record.key}`, {ifAvailable: true}, (lock) => (lock ? work() : null));
    } else {
      work();
    }
  }

  /** Start uploading the files of a form to a workspace; its other fields are their classification. */
  async function start(formElement, {workspaceId, workspaceName}) {
    const data = new FormData(formElement);
    const files = data.getAll('dataset_files').filter((value) => value instanceof File && value.name);
    const form = {};
    for (const [name, value] of data.entries()) {
      if (name === 'dataset_files') continue;
      (form[name] ||= []).push(String(value));
    }
    const {response, payload} = await request('/api/uploads', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({workspace_id: workspaceId, files: files.map((file) => ({name: file.name, size: file.size})), form}),
    });
    if (!response.ok) throw new Error(payload.detail || 'The upload could not start.');
    const record = {
      key: `${workspaceId}/${payload.upload_id}`, upload_id: payload.upload_id, workspace_id: workspaceId,
      workspace_name: payload.workspace_name || workspaceName, username: config.username, files,
      names: files.map((file) => file.name), started_at: Date.now() / 1000,
    };
    const stored = await saveRecord(record);
    publish(record, {status: 'processing', progress: 0, detail: 'Starting upload', duration_seconds: 0});
    run(record);
    return {...record, persisted: Boolean(stored)};
  }

  window.DriveTestUploads = {start};
  listRecords().then((records) => records.forEach((record) => {
    publish(record, {status: 'processing', progress: 0, detail: 'Resuming upload'});
    run(record);
  }));
})();
