function formatAxisValue(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 100) return numeric.toFixed(0);
  if (Math.abs(numeric) >= 10) return numeric.toFixed(1).replace(/\.0$/, '');
  return numeric.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

function configureCalculatedDimensionSourceMenu(sourceMenu, overlay) {
  let leaveTimer = null;
  const closeMenu = () => { sourceMenu.open = false; };
  const clearLeaveTimer = () => { if (leaveTimer) { window.clearTimeout(leaveTimer); leaveTimer = null; } };
  sourceMenu.addEventListener('pointerenter', clearLeaveTimer);
  sourceMenu.addEventListener('pointerleave', () => {
    clearLeaveTimer();
    leaveTimer = window.setTimeout(closeMenu, 700);
  });
  sourceMenu.addEventListener('focusout', () => {
    window.setTimeout(() => { if (!sourceMenu.matches(':focus-within')) closeMenu(); }, 0);
  });
  overlay.addEventListener('pointerdown', (event) => {
    if (!sourceMenu.contains(event.target)) closeMenu();
  });
}

const formatCalculatedDimensionAliases = (value) => String(value || '')
  .split(/\s+(?:OR)\s+|\s*\|\s*/i)
  .map((alias) => alias.trim().replace(/^\[\s*/, '').replace(/\s*\]$/, ''))
  .filter(Boolean)
  .map((alias) => `[${alias}]`)
  .join(' OR ');

const formatCalculatedDimensionRuleAliases = (value) => String(value || '')
  .split(';')
  .map((clause) => {
    const match = clause.trim().match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i);
    return match
      ? `${formatCalculatedDimensionAliases(match[1])} ${match[2]} ${match[3].trim()}`
      : clause.trim();
  })
  .filter(Boolean)
  .join('; ');

function configureCalculatedDimensionFieldAutocomplete(input, getColumns) {
  const ownerDocument = input.ownerDocument;
  const ownerWindow = ownerDocument.defaultView || window;
  const menu = ownerDocument.createElement('div');
  menu.className = 'calculated-dimension-field-suggestions';
  menu.setAttribute('role', 'listbox');
  menu.hidden = true;
  const menuPortal = input.closest('.calculated-dimensions-overlay') || ownerDocument.body;
  menuPortal.append(menu);
  let openBracket = -1;
  let activeIndex = -1;

  const close = () => {
    menu.hidden = true;
    menu.replaceChildren();
    openBracket = -1;
    activeIndex = -1;
  };
  const position = () => {
    if (menu.hidden) return;
    const bounds = input.getBoundingClientRect();
    menu.style.left = `${Math.max(8, bounds.left)}px`;
    menu.style.top = `${Math.min(bounds.bottom + 4, ownerWindow.innerHeight - menu.offsetHeight - 8)}px`;
    menu.style.width = `${Math.max(bounds.width, 260)}px`;
  };
  const choose = (column) => {
    if (openBracket < 0) return;
    const caret = input.selectionStart ?? input.value.length;
    input.value = `${input.value.slice(0, openBracket)}[${column}]${input.value.slice(caret)}`;
    const nextCaret = openBracket + column.length + 2;
    input.setSelectionRange(nextCaret, nextCaret);
    input.dispatchEvent(new ownerWindow.Event('input', {bubbles: true}));
    close();
    input.focus();
  };
  const setActive = (index) => {
    const options = Array.from(menu.querySelectorAll('button'));
    if (!options.length) return;
    activeIndex = (index + options.length) % options.length;
    options.forEach((option, optionIndex) => option.classList.toggle('is-active', optionIndex === activeIndex));
    options[activeIndex].scrollIntoView({block: 'nearest'});
  };
  const refresh = () => {
    const caret = input.selectionStart ?? input.value.length;
    const beforeCaret = input.value.slice(0, caret);
    openBracket = beforeCaret.lastIndexOf('[');
    if (openBracket < 0 || beforeCaret.slice(openBracket + 1).includes(']')) {
      close();
      return;
    }
    const query = beforeCaret.slice(openBracket + 1);
    if (/[\r\n\[\]]/.test(query)) {
      close();
      return;
    }
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const columns = [...new Set((getColumns() || []).map((column) => String(column).trim()).filter(Boolean))]
      .filter((column) => column.toLocaleLowerCase().startsWith(normalizedQuery))
      .sort((left, right) => left.localeCompare(right));
    menu.replaceChildren();
    columns.forEach((column) => {
      const option = ownerDocument.createElement('button');
      option.type = 'button';
      option.setAttribute('role', 'option');
      option.textContent = column;
      option.addEventListener('pointerdown', (event) => event.preventDefault());
      option.addEventListener('click', () => choose(column));
      menu.append(option);
    });
    if (!columns.length) {
      const empty = ownerDocument.createElement('span');
      empty.className = 'calculated-dimension-field-suggestions-empty';
      empty.textContent = 'No matching fields';
      menu.append(empty);
    }
    menu.hidden = false;
    activeIndex = -1;
    position();
  };
  const handleKeydown = (event) => {
    if (menu.hidden) return;
    const options = Array.from(menu.querySelectorAll('button'));
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      options[activeIndex]?.click();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  };
  const handleOutsidePointer = (event) => {
    if (event.target !== input && !menu.contains(event.target)) close();
  };
  input.addEventListener('input', refresh);
  input.addEventListener('click', refresh);
  input.addEventListener('keydown', handleKeydown);
  ownerDocument.addEventListener('pointerdown', handleOutsidePointer, true);
  ownerWindow.addEventListener('resize', position);
  ownerWindow.addEventListener('scroll', position, true);
  return {
    refresh,
    close,
    isOpen: () => !menu.hidden,
    destroy: () => {
      input.removeEventListener('input', refresh);
      input.removeEventListener('click', refresh);
      input.removeEventListener('keydown', handleKeydown);
      ownerDocument.removeEventListener('pointerdown', handleOutsidePointer, true);
      ownerWindow.removeEventListener('resize', position);
      ownerWindow.removeEventListener('scroll', position, true);
      menu.remove();
    },
  };
}

const autoCalculatedFieldJobStorageKey = 'dashboard-analytic:auto-calculated-field-jobs';
const storedAutoCalculatedFieldJobs = () => {
  try {
    const value = JSON.parse(window.localStorage.getItem(autoCalculatedFieldJobStorageKey) || '[]');
    return Array.isArray(value) ? value : [];
  } catch (_error) {
    return [];
  }
};

const materializationJobProgressPercent = (job) => {
  const status = String(job?.status || '').toLowerCase();
  if (['queued', 'pending'].includes(status)) return 0;
  const total = Math.max(Number(job?.total) || 0, 0);
  const completed = Math.max(Number(job?.completed) || 0, 0);
  if (status === 'ready') return 100;
  if (!total) return 0;
  const maximum = status === 'processing' ? 99 : 100;
  return Math.min(maximum, Math.max(0, Math.round(completed * 100 / total)));
};

function syncCombinedDatasetStopButton(row, recreation = {}) {
  if (!(row instanceof HTMLElement)) return;
  const actions = row.querySelector('.queue-actions');
  const recreateButton = row.querySelector('[data-combined-dataset-recreate]');
  if (!(actions instanceof HTMLElement)) return;
  let stopButton = actions.querySelector('[data-combined-dataset-stop]');
  const active = Boolean(recreation.active && recreation.stopUrl && recreation.stopTaskId);
  if (!active) {
    stopButton?.remove();
    return;
  }
  if (!(stopButton instanceof HTMLButtonElement)) {
    stopButton = document.createElement('button');
    stopButton.type = 'button';
    stopButton.className = 'combined-dataset-stop-button';
    stopButton.setAttribute('data-combined-dataset-stop', '');
    stopButton.textContent = 'Stop';
    stopButton.title = 'Stop combined table recreation';
    stopButton.setAttribute('aria-label', stopButton.title);
    actions.insertBefore(stopButton, recreateButton || null);
  }
  stopButton.dataset.stopUrl = String(recreation.stopUrl);
  stopButton.dataset.stopTaskId = String(recreation.stopTaskId);
  stopButton.dataset.combinedName = String(recreation.combinedName || 'the combined CDR table');
}

function updateCombinedDatasetRecreationRow(job) {
  if (job.operation !== 'combined_recreation' || !job.combined_kind) return;
  const row = document.querySelector(`[data-combined-dataset-row][data-dataset-kind="${job.combined_kind}"]`);
  if (!(row instanceof HTMLElement)) return;
  const processing = ['queued', 'processing'].includes(job.status);
  const failed = ['failed', 'stopped'].includes(job.status);
  const percent = materializationJobProgressPercent(job);
  const status = row.querySelector('[data-combined-dataset-status]');
  const bar = row.querySelector('[data-combined-dataset-progress-bar]');
  const label = row.querySelector('[data-combined-dataset-progress-percent]');
  syncCombinedDatasetStopButton(row, {
    active: processing,
    stopUrl: job.workspace_id ? `/api/background-tasks/${job.workspace_id}/stop` : '',
    stopTaskId: job.id ? `auto-fields:${job.id}` : '',
    combinedName: `CDR-${String(job.combined_kind).replace(/^./, (value) => value.toUpperCase())} (combined)`,
  });
  row.classList.toggle('combined-dataset-ready', !processing && !failed);
  row.classList.toggle('combined-dataset-warning', processing || failed);
  if (status instanceof HTMLElement) {
    status.className = `queue-status-pill queue-status-${failed ? 'failed' : processing ? 'processing' : 'ready'}`;
    status.textContent = job.status === 'stopped' ? 'Stopped' : failed ? 'Failed' : processing ? (job.status === 'queued' ? 'Queued' : 'Recreating') : 'Ready';
  }
  if (bar instanceof HTMLElement) {
    bar.className = `progress-bar status-${failed ? 'failed' : processing ? 'processing' : 'ready'}`;
    bar.style.width = `${percent}%`;
  }
  if (label instanceof HTMLElement) label.textContent = `${percent}%`;
}

function monitorAutoCalculatedFieldJob(statusUrl, notice = '') {
  if (!statusUrl) return;
  const saved = new Set(storedAutoCalculatedFieldJobs());
  saved.add(statusUrl);
  window.localStorage.setItem(autoCalculatedFieldJobStorageKey, JSON.stringify([...saved]));
  if (notice) showInfoDialog(notice, {title: 'Auto-calculated Fields'});
  const poll = async () => {
    try {
      const response = await fetch(statusUrl, {credentials: 'same-origin'});
      const job = await response.json().catch(() => ({}));
      if (response.status === 404) {
        const current = new Set(storedAutoCalculatedFieldJobs());
        current.delete(statusUrl);
        window.localStorage.setItem(autoCalculatedFieldJobStorageKey, JSON.stringify([...current]));
        showInfoDialog('The background job is no longer available. Reopen the workspace to retry any interrupted materialization.', {title: 'Materialization status unavailable', tone: 'error'});
        return;
      }
      if (!response.ok) throw new Error(job.detail || 'Unable to read materialization progress.');
      updateCombinedDatasetRecreationRow(job);
      window.dispatchEvent(new CustomEvent('auto-calculated-field-job-status', {detail: job}));
      if (job.status === 'ready' || job.status === 'failed' || job.status === 'stopped') {
        const current = new Set(storedAutoCalculatedFieldJobs());
        current.delete(statusUrl);
        window.localStorage.setItem(autoCalculatedFieldJobStorageKey, JSON.stringify([...current]));
        document.querySelectorAll('[data-combined-dataset-recreate]').forEach((button) => { button.disabled = false; });
        if (job.status === 'ready') {
          window.dispatchEvent(new CustomEvent('workspace-dataset-table-refresh-requested'));
          showInfoDialog(job.message || 'Auto-calculated fields are ready.', {
            title: 'Materialization complete',
          });
        } else {
          if (job.status === 'stopped') {
            window.dispatchEvent(new CustomEvent('workspace-dataset-table-refresh-requested'));
          }
          showInfoDialog(job.error || job.message || 'The CDR tables could not be updated.', {title: job.status === 'stopped' ? 'Materialization stopped' : 'Materialization failed', tone: 'error'});
        }
        return;
      }
      window.setTimeout(poll, 1200);
    } catch (_error) {
      window.setTimeout(poll, 2500);
    }
  };
  window.setTimeout(poll, 500);
}

window.addEventListener('load', () => {
  const params = new URLSearchParams(window.location.search);
  const redirectedJob = params.get('auto_fields_job_id');
  const pending = new Set(storedAutoCalculatedFieldJobs());
  if (redirectedJob) pending.add(`/api/workspace/auto-calculated-fields/materialization/${redirectedJob}`);
  pending.forEach((statusUrl) => monitorAutoCalculatedFieldJob(statusUrl));
});

document.querySelectorAll('[data-combined-dataset-recreate]').forEach((button) => {
  button.addEventListener('click', async () => {
    const accepted = await showConfirmDialog(
      `Check and migrate every individual CDR table of this type, then recreate ${button.dataset.combinedName || 'the combined CDR table'}? This runs in the background and can take several minutes. If a recreation of the same CDR type is already running, it will be stopped and restarted.`,
      {title: 'Recreate combined table', confirmLabel: 'Recreate table', tone: 'warning'},
    );
    if (!accepted) return;
    button.disabled = true;
    try {
      const response = await fetch(button.dataset.recreateUrl || '', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to recreate the combined CDR table.');
      monitorAutoCalculatedFieldJob(payload.materialization_status_url);
      // A confirmed second click intentionally restarts the same CDR type.
      button.disabled = false;
    } catch (error) {
      button.disabled = false;
      showInfoDialog(error instanceof Error ? error.message : 'Unable to recreate the combined CDR table.', {
        title: 'Combined CDR recreation failed', tone: 'error',
      });
    }
  });
});

document.addEventListener('click', async (event) => {
  const button = event.target instanceof Element ? event.target.closest('[data-combined-dataset-stop]') : null;
  if (!(button instanceof HTMLButtonElement)) return;
  const accepted = await showConfirmDialog(
    `Stop recreating ${button.dataset.combinedName || 'the combined CDR table'}?`,
    {title: 'Stop combined table recreation', confirmLabel: 'Stop recreation', tone: 'warning'},
  );
  if (!accepted) return;
  button.disabled = true;
  try {
    const body = new URLSearchParams({task_id: String(button.dataset.stopTaskId || '')});
    const response = await fetch(String(button.dataset.stopUrl || ''), {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json'}, body,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || 'The combined table recreation could not be stopped.');
    }
    const status = button.closest('[data-combined-dataset-row]')?.querySelector('[data-combined-dataset-status]');
    if (status instanceof HTMLElement) status.textContent = 'Stopping';
    window.dispatchEvent(new CustomEvent('workspace-dataset-table-refresh-requested'));
  } catch (error) {
    button.disabled = false;
    showInfoDialog(error instanceof Error ? error.message : 'The combined table recreation could not be stopped.', {
      title: 'Stop recreation failed', tone: 'error',
    });
  }
});

document.querySelectorAll('[data-workspace-calculated-dimensions-panel]').forEach((host) => {
  const manage = host.querySelector('[data-workspace-manage-calculated-dimensions]');
  const progressPanel = document.querySelector('[data-auto-calculated-field-progress]');
  const progressStatus = document.querySelector('[data-auto-calculated-field-progress-status]');
  const progressQueuedStatus = document.querySelector('[data-auto-calculated-field-queued-status]');
  const progressJobList = document.querySelector('[data-auto-calculated-field-job-list]');
  const rematerializeButton = document.querySelector('[data-auto-calculated-field-rematerialize]');
  let progressTimer = null;
  const materializationJobLabel = (job) => {
    if (job.operation === 'combined_recreation' && job.combined_kind) {
      return `Combined CDR-${String(job.combined_kind).toUpperCase()}`;
    }
    if (job.operation) return 'Auto-calculated Fields';
    return 'Materialized CDR tables';
  };
  const renderMaterializationJobs = (jobs) => {
    if (!(progressJobList instanceof HTMLElement)) return;
    progressJobList.querySelectorAll('.auto-calculated-field-job:not([data-materialization-job-key])')
      .forEach((placeholder) => placeholder.remove());
    const retainedKeys = new Set();
    let insertionPoint = progressJobList.firstElementChild;
    jobs.forEach((job, jobIndex) => {
      const jobKey = String(job.id || `${job.operation || 'materialization'}:${job.combined_kind || job.workspace_id || jobIndex}`);
      retainedKeys.add(jobKey);
      const processing = ['queued', 'processing'].includes(job.status);
      const failed = ['failed', 'stopped'].includes(job.status);
      let article = Array.from(progressJobList.querySelectorAll('[data-materialization-job-key]'))
        .find((item) => item.dataset.materializationJobKey === jobKey);
      if (!(article instanceof HTMLElement)) {
        article = document.createElement('article');
        article.dataset.materializationJobKey = jobKey;
        article.innerHTML = `
          <div class="auto-calculated-field-job-heading">
            <strong data-materialization-job-label></strong>
            <span data-materialization-job-state></span>
          </div>
          <div class="auto-calculated-field-progress-row">
            <div class="auto-calculated-field-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">
              <span class="auto-calculated-field-progress-bar"></span>
              <span class="auto-calculated-field-progress-percent"></span>
            </div>
          </div>
          <p class="form-note auto-calculated-field-job-message" data-materialization-job-message></p>
        `;
      }
      if (article !== insertionPoint) progressJobList.insertBefore(article, insertionPoint);
      insertionPoint = article.nextElementSibling;
      article.className = `auto-calculated-field-job${processing ? ' is-processing' : ''}${failed ? ' is-failed' : ''}`;
      const computedPercent = materializationJobProgressPercent(job);
      const previousPercent = Number(article.dataset.progressPercent || 0);
      const percent = job.status === 'processing' && article.dataset.progressStatus === 'processing'
        ? Math.max(previousPercent, computedPercent)
        : computedPercent;
      article.dataset.progressPercent = String(percent);
      article.dataset.progressStatus = String(job.status || '');
      const label = article.querySelector('[data-materialization-job-label]');
      const state = article.querySelector('[data-materialization-job-state]');
      const progressRow = article.querySelector('.auto-calculated-field-progress-row');
      const track = article.querySelector('.auto-calculated-field-progress-track');
      const bar = article.querySelector('.auto-calculated-field-progress-bar');
      const percentLabel = article.querySelector('.auto-calculated-field-progress-percent');
      const copy = article.querySelector('[data-materialization-job-message]');
      if (label instanceof HTMLElement) label.textContent = materializationJobLabel(job);
      const stateLabel = job.cancel_requested ? 'Stopping' : job.status === 'queued' ? 'Queued' : job.status === 'pending' ? 'Pending' : job.status === 'processing' ? 'In progress' : job.status === 'stopped' ? 'Stopped' : job.status === 'failed' ? 'Failed' : 'Up to date';
      if (state instanceof HTMLElement) state.textContent = `${stateLabel} · ${percent}%`;
      if (track instanceof HTMLElement) {
        track.setAttribute('aria-label', `${materializationJobLabel(job)} materialization`);
        track.setAttribute('aria-valuenow', String(percent));
      }
      if (bar instanceof HTMLElement && bar.style.width !== `${percent}%`) bar.style.width = `${percent}%`;
      if (percentLabel instanceof HTMLElement) percentLabel.textContent = `${percent}%`;
      if (copy instanceof HTMLElement) copy.textContent = job.error || job.message || 'All materialized fields are up to date.';
      const existingStop = progressRow?.querySelector('.auto-calculated-field-stop-button');
      if (processing && job.workspace_id) {
        const stop = existingStop instanceof HTMLButtonElement ? existingStop : document.createElement('button');
        if (!(existingStop instanceof HTMLButtonElement)) {
          stop.type = 'button';
          stop.className = 'auto-calculated-field-stop-button combined-dataset-stop-button';
          stop.textContent = 'Stop';
          stop.title = 'Stop materialization';
          stop.setAttribute('aria-label', stop.title);
          stop.addEventListener('click', async () => {
            const accepted = await showConfirmDialog(
              `Stop “${stop.dataset.jobLabel || 'Auto-calculated Fields'}”?`,
              {title: 'Stop materialization', confirmLabel: 'Stop materialization', tone: 'warning'},
            );
            if (!accepted) return;
            stop.disabled = true;
            try {
              const body = new URLSearchParams({task_id: stop.dataset.taskId || ''});
              const response = await fetch(stop.dataset.stopUrl || '', {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json'}, body,
              });
              if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.detail || 'The materialization task could not be stopped.');
              }
              if (state instanceof HTMLElement) state.textContent = `Stopping · ${article.dataset.progressPercent || 0}%`;
              window.setTimeout(refreshMaterializationProgress, 250);
            } catch (error) {
              stop.disabled = false;
              showInfoDialog(error instanceof Error ? error.message : 'The materialization task could not be stopped.', {
                title: 'Stop materialization failed', tone: 'error',
              });
            }
          });
          progressRow?.append(stop);
        }
        stop.dataset.jobLabel = materializationJobLabel(job);
        stop.dataset.taskId = job.id ? `auto-fields:${job.id}` : `auto-fields-state:${job.workspace_id}`;
        stop.dataset.stopUrl = `/api/background-tasks/${job.workspace_id}/stop`;
        stop.disabled = Boolean(job.cancel_requested);
      } else {
        existingStop?.remove();
      }
    });
    progressJobList.querySelectorAll('[data-materialization-job-key]').forEach((article) => {
      if (!retainedKeys.has(article.dataset.materializationJobKey || '')) article.remove();
    });
  };
  const refreshMaterializationProgress = async () => {
    if (!(progressPanel instanceof HTMLElement) || !progressPanel.dataset.statusUrl) return;
    try {
      const response = await fetch(progressPanel.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store'});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to read materialization progress.');
      const listedJobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      const activeJobs = listedJobs.length
        ? listedJobs
        : ['queued', 'processing'].includes(payload.status) ? [payload] : [];
      const jobs = activeJobs.length ? activeJobs : [payload];
      const processingJobs = activeJobs.filter((job) => job.status === 'processing');
      const queuedJobs = activeJobs.filter((job) => job.status === 'queued');
      const hasActiveJobs = processingJobs.length > 0 || queuedJobs.length > 0;
      const failed = !hasActiveJobs && jobs.some((job) => ['failed', 'stopped'].includes(job.status));
      const stopped = failed && jobs.some((job) => job.status === 'stopped');
      const pending = !hasActiveJobs && jobs.some((job) => job.status === 'pending');
      progressPanel.classList.toggle('is-processing', hasActiveJobs);
      progressPanel.classList.toggle('is-failed', failed);
      progressPanel.classList.toggle('is-stopped', stopped);
      if (rematerializeButton instanceof HTMLButtonElement) rematerializeButton.disabled = hasActiveJobs;
      if (progressStatus instanceof HTMLElement) {
        progressStatus.className = `status-pill status-${failed ? 'failed' : hasActiveJobs || pending ? 'processing' : 'ready'}`;
        progressStatus.textContent = stopped ? 'Stopped' : failed ? 'Failed' : hasActiveJobs
          ? `${processingJobs.length} in progress` : pending ? 'Pending' : 'Up to date';
      }
      if (progressQueuedStatus instanceof HTMLElement) {
        progressQueuedStatus.hidden = queuedJobs.length === 0;
        progressQueuedStatus.className = 'status-pill status-processing';
        progressQueuedStatus.textContent = `${queuedJobs.length} queued`;
      }
      renderMaterializationJobs(jobs);
      if (progressTimer) window.clearTimeout(progressTimer);
      progressTimer = window.setTimeout(refreshMaterializationProgress, hasActiveJobs ? 900 : 5000);
    } catch (error) {
      renderMaterializationJobs([{
        status: 'failed', error: error.message || 'Materialization status is temporarily unavailable.',
      }]);
      if (progressTimer) window.clearTimeout(progressTimer);
      progressTimer = window.setTimeout(refreshMaterializationProgress, 5000);
    }
  };
  window.addEventListener('auto-calculated-field-job-status', refreshMaterializationProgress);
  let dimensions = [];
  let availableDimensionColumns = {};
  try { dimensions = JSON.parse(host.dataset.calculatedDimensions || '[]'); } catch (_error) { dimensions = []; }
  const saveDimensions = async (next, renames = [], materialize = true, showNotice = true) => {
    const response = await fetch(host.dataset.saveUrl, {
      method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dimensions: next, renames, materialize}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Unable to save auto-calculated fields.');
    dimensions = payload.dimensions || next;
    if (payload.materialization_status_url) {
      monitorAutoCalculatedFieldJob(payload.materialization_status_url, showNotice ? payload.notice : '');
      refreshMaterializationProgress();
    } else if (showNotice && payload.notice) {
      showInfoDialog(payload.notice, {title: 'Auto-calculated Fields'});
    }
    return payload;
  };
  refreshMaterializationProgress();
  rematerializeButton?.addEventListener('click', async () => {
    const accepted = await showConfirmDialog(
      'All auto-calculated fields will be rematerialized in every applicable CDR table. This can take a while and will run in the background. Continue?',
      {title: 'Rematerialize Auto-calculated Fields', confirmLabel: 'Rematerialize All', tone: 'warning'},
    );
    if (!accepted || !(rematerializeButton instanceof HTMLButtonElement)) return;
    rematerializeButton.disabled = true;
    try {
      const response = await fetch('/api/workspace/auto-calculated-fields/rematerialize', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to rematerialize auto-calculated fields.');
      monitorAutoCalculatedFieldJob(payload.materialization_status_url, payload.notice);
      await refreshMaterializationProgress();
    } catch (error) {
      rematerializeButton.disabled = false;
      showInfoDialog(error instanceof Error ? error.message : 'Unable to rematerialize auto-calculated fields.', {
        title: 'Auto-calculated Fields', tone: 'error',
      });
    }
  });
  manage?.addEventListener('click', async () => {
    try {
      const response = await fetch(host.dataset.saveUrl, {credentials: 'same-origin', cache: 'no-store'});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to load auto-calculated fields.');
      dimensions = Array.isArray(payload.dimensions) ? payload.dimensions : [];
      availableDimensionColumns = payload.columns && typeof payload.columns === 'object' ? payload.columns : {};
      host.dataset.calculatedDimensions = JSON.stringify(dimensions);
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to load auto-calculated fields.', {
        title: 'Auto-calculated Fields', tone: 'error',
      });
      return;
    }
    const overlay = document.createElement('div'); overlay.className = 'confirm-overlay calculated-dimensions-overlay';
    const panel = document.createElement('section'); panel.className = 'confirm-panel calculated-dimensions-dialog';
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    const header = document.createElement('div'); header.className = 'catalogue-chart-preview-header';
    const heading = document.createElement('div'); heading.innerHTML = '<p class="eyebrow">Active Workspace</p><h3>Auto-calculated Fields</h3>';
    const close = document.createElement('button'); close.type = 'button'; close.className = 'calculated-dimensions-close calculated-dimensions-icon-close report-chart-viewer-close'; close.textContent = '×'; close.setAttribute('aria-label', 'Close auto-calculated fields');
    header.append(heading, close);
    const note = document.createElement('p'); note.className = 'form-note'; note.textContent = 'Use ordered condition => result rules or one Tableau-style IF / THEN / ELSEIF / ELSE / END expression. Type [ to select a source field from the chosen CDR types. Expressions may be nested and comparisons ignore case.';
    const list = document.createElement('div'); list.className = 'calculated-dimensions-list';
    const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Add Auto-calculated Field';
    const managerActions = document.createElement('div'); managerActions.className = 'calculated-dimensions-manager-actions';
    const panelClose = document.createElement('button'); panelClose.type = 'button'; panelClose.className = 'calculated-dimensions-close'; panelClose.textContent = 'Close';
    const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save'; save.disabled = true;
    const saveAndMaterialize = document.createElement('button'); saveAndMaterialize.type = 'button'; saveAndMaterialize.textContent = 'Save & Materialize'; saveAndMaterialize.disabled = true;
    managerActions.append(add, save, saveAndMaterialize, panelClose);
    const form = document.createElement('div'); form.className = 'calculated-dimension-editor'; form.hidden = true;
    panel.append(header, note, list, managerActions, form); overlay.append(panel); document.body.append(overlay);
    let savedEditorState = '';
    let fieldAutocompleteControllers = [];
    let persistedDimensions = JSON.parse(JSON.stringify(dimensions));
    const pendingRenames = new Map();
    const recordPendingRename = (from, to) => {
      let original = from;
      for (const [candidate, current] of pendingRenames) {
        if (current === from) {
          original = candidate;
          pendingRenames.delete(candidate);
          break;
        }
      }
      if (original !== to) pendingRenames.set(original, to);
    };
    const hasPendingChanges = () => JSON.stringify(dimensions) !== JSON.stringify(persistedDimensions);
    const updateSaveActions = () => {
      const disabled = !hasPendingChanges();
      save.disabled = disabled;
      saveAndMaterialize.disabled = disabled;
    };
    const editorState = () => JSON.stringify(Array.from(form.querySelectorAll('input, textarea')).map((input) => ({
      type: input.type, value: input.value, checked: input.checked,
    })));
    const hasUnsavedEditorChanges = () => !form.hidden && editorState() !== savedEditorState;
    const clearFieldAutocompletes = () => {
      fieldAutocompleteControllers.forEach((controller) => controller.destroy());
      fieldAutocompleteControllers = [];
    };
    const finish = () => {
      clearFieldAutocompletes();
      window.removeEventListener('keydown', handleEscape, true);
      overlay.remove();
    };
    const requestFinish = async () => {
      if (hasUnsavedEditorChanges() && !await showConfirmDialog(
        'This Auto-calculated Field has unsaved changes. Close without saving them?',
        {title: 'Unsaved Auto-calculated Field', confirmLabel: 'Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return;
      if (hasPendingChanges() && !await showConfirmDialog(
        'There are applied Auto-calculated Field changes that have not been saved. Close and discard them?',
        {title: 'Unsaved Auto-calculated Fields', confirmLabel: 'Discard and Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return;
      finish();
    };
    const returnToList = async (confirmDiscard = true) => {
      if (form.hidden) return false;
      if (confirmDiscard && hasUnsavedEditorChanges() && !await showConfirmDialog(
        'This Auto-calculated Field has unsaved changes. Close without saving them?',
        {title: 'Unsaved Auto-calculated Field', confirmLabel: 'Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return false;
      clearFieldAutocompletes();
      form.hidden = true;
      list.hidden = false;
      restoreManagerActions();
      render();
      updateSaveActions();
      add.focus();
      return true;
    };
    const handleEscape = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (fieldAutocompleteControllers.some((controller) => controller.isOpen())) {
        fieldAutocompleteControllers.forEach((controller) => controller.close());
        return;
      }
      if (form.hidden) void requestFinish(); else void returnToList();
    };
    close.addEventListener('click', () => { void requestFinish(); });
    panelClose.addEventListener('click', () => {
      if (form.hidden) void requestFinish(); else void returnToList();
    });
    overlay.addEventListener('click', (event) => { if (event.target === overlay) void requestFinish(); });
    window.addEventListener('keydown', handleEscape, true);
    const restoreManagerActions = () => { managerActions.hidden = false; managerActions.append(add, save, saveAndMaterialize, panelClose); };
    const edit = (index = null) => {
      const current = index === null ? {name: '', sources: ['cdr-data'], default: '', default_from: '', rules: []} : dimensions[index];
      clearFieldAutocompletes();
      form.replaceChildren(); form.hidden = false; list.hidden = true; managerActions.hidden = true;
      const inputField = (caption, value = '') => {
        const label = document.createElement('label'); label.textContent = caption;
        const input = document.createElement('input'); input.value = value; label.append(input); form.append(label); return input;
      };
      const name = inputField('Name', current.name || '');
      const fallback = inputField('Default value (optional)', current.default || '');
      const fallbackField = inputField('Default source fields (optional, use [Field A] OR [Field B])', current.default_from || '');
      const sources = document.createElement('div'); sources.className = 'calculated-dimension-sources';
      const sourcesLabel = document.createElement('span'); sourcesLabel.textContent = 'Available for';
      const sourceMenu = document.createElement('details'); sourceMenu.className = 'calculated-dimension-source-menu';
      const sourceSummary = document.createElement('summary');
      const sourceChoices = document.createElement('div'); sourceChoices.className = 'calculated-dimension-source-choices';
      const updateSourceSummary = () => {
        const selected = Array.from(sourceChoices.querySelectorAll('input:checked')).map((item) => item.value.toUpperCase());
        sourceSummary.textContent = selected.length ? selected.join(', ') : 'Select CDR types';
      };
      ['cdr-data', 'cdr-voice', 'cdr-speech'].forEach((source) => {
        const label = document.createElement('label'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = source;
        checkbox.checked = (current.sources || []).includes(source); label.append(checkbox, document.createTextNode(source.toUpperCase())); sourceChoices.append(label);
      });
      sourceMenu.append(sourceSummary, sourceChoices); sourceMenu.addEventListener('change', () => {
        updateSourceSummary();
        fieldAutocompleteControllers.forEach((controller) => controller.refresh());
      }); configureCalculatedDimensionSourceMenu(sourceMenu, overlay); updateSourceSummary(); sources.append(sourcesLabel, sourceMenu); form.append(sources);
      const rulesLabel = document.createElement('label'); rulesLabel.className = 'calculated-dimension-rules'; rulesLabel.textContent = 'Rules';
      const rules = document.createElement('textarea'); rules.placeholder = "[Test_Result] IN (Completed, Visible Completed) => Success\n\nor\n\nIF ([Mean Data Rate] < 1) THEN 'below1'\nELSE 'Above'\nEND";
      rules.value = current.expression || (current.rules || []).map((rule) => `${rule.when} => ${rule.value}`).join('\n'); rulesLabel.append(rules); form.append(rulesLabel);
      const selectedColumns = () => Array.from(sourceChoices.querySelectorAll('input:checked'))
        .flatMap((checkbox) => [
          ...(availableDimensionColumns[checkbox.value] || []),
          ...dimensions.filter((dimension) => (dimension.sources || []).includes(checkbox.value)).map((dimension) => dimension.name),
        ]);
      fieldAutocompleteControllers = [fallbackField, rules]
        .map((field) => configureCalculatedDimensionFieldAutocomplete(field, selectedColumns));
      const actions = document.createElement('div'); actions.className = 'confirm-actions calculated-dimension-rules';
      const discard = document.createElement('button'); discard.type = 'button'; discard.className = 'calculated-dimensions-close'; discard.textContent = 'Discard';
      const apply = document.createElement('button'); apply.type = 'button'; apply.textContent = 'Apply'; actions.append(discard, apply); form.append(actions);
      discard.addEventListener('click', () => { void returnToList(false); });
      apply.addEventListener('click', async () => {
        try {
          const ruleText = rules.value.trim();
          const isExpression = /^IF\b/i.test(ruleText);
          const parsedRules = isExpression ? [] : ruleText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
            const separator = line.lastIndexOf('=>');
            if (separator < 1) throw new Error(`Invalid rule '${line}'. Use condition => result or a complete IF / THEN / END expression.`);
            return {when: formatCalculatedDimensionRuleAliases(line.slice(0, separator)), value: line.slice(separator + 2).trim()};
          });
          const dimension = {name: name.value.trim(), sources: Array.from(sources.querySelectorAll('input:checked')).map((item) => item.value), default: fallback.value, default_from: formatCalculatedDimensionAliases(fallbackField.value), rules: parsedRules, expression: isExpression ? ruleText : ''};
          const next = [...dimensions]; if (index === null) next.push(dimension); else next[index] = dimension;
          const rename = index === null || current.name === dimension.name ? null : {from: current.name, to: dimension.name};
          dimensions = next;
          if (rename) recordPendingRename(rename.from, rename.to);
          await returnToList(false);
        } catch (error) { showInfoDialog(error.message || 'Unable to save auto-calculated field.', {title: 'Auto-calculated Fields', tone: 'error'}); }
      });
      savedEditorState = editorState();
      name.focus();
    };
    const render = () => {
      list.replaceChildren();
      dimensions.forEach((dimension, index) => {
        const item = document.createElement('div'); item.className = 'calculated-dimension-item';
        const orderActions = document.createElement('div'); orderActions.className = 'calculated-dimension-order-actions';
        const moveUp = document.createElement('button'); moveUp.type = 'button'; moveUp.textContent = '↑'; moveUp.title = `Move ${dimension.name} up`; moveUp.setAttribute('aria-label', moveUp.title); moveUp.disabled = index === 0;
        const moveDown = document.createElement('button'); moveDown.type = 'button'; moveDown.textContent = '↓'; moveDown.title = `Move ${dimension.name} down`; moveDown.setAttribute('aria-label', moveDown.title); moveDown.disabled = index === dimensions.length - 1;
        moveUp.addEventListener('click', () => {
          [dimensions[index - 1], dimensions[index]] = [dimensions[index], dimensions[index - 1]];
          render(); updateSaveActions();
        });
        moveDown.addEventListener('click', () => {
          [dimensions[index], dimensions[index + 1]] = [dimensions[index + 1], dimensions[index]];
          render(); updateSaveActions();
        });
        orderActions.append(moveUp, moveDown);
        const identity = document.createElement('div'); identity.innerHTML = `<strong></strong><p></p>`; identity.querySelector('strong').textContent = dimension.name; identity.querySelector('p').textContent = (dimension.sources || []).map((source) => source.toUpperCase()).join(' · ');
        const summary = document.createElement('div'); summary.className = 'calculated-dimension-rule-summary';
        (dimension.rules || []).forEach((rule, ruleIndex) => {
          const line = document.createElement('div');
          const number = document.createElement('strong'); number.textContent = `${ruleIndex + 1}.`;
          const condition = document.createElement('code'); condition.textContent = rule.when || 'ELSE';
          const arrow = document.createElement('span'); arrow.textContent = '→';
          const result = document.createElement('b'); result.textContent = rule.value;
          line.append(number, condition, arrow, result); summary.append(line);
        });
        if (dimension.expression) {
          const expression = document.createElement('div'); expression.className = 'calculated-dimension-expression';
          const expressionLabel = document.createElement('strong'); expressionLabel.textContent = 'IF expression';
          const expressionText = document.createElement('pre'); expressionText.textContent = dimension.expression;
          expression.append(expressionLabel, expressionText); summary.append(expression);
        }
        if (dimension.default_from || dimension.default) {
          const fallbackLine = document.createElement('div'); fallbackLine.className = 'calculated-dimension-fallback';
          fallbackLine.textContent = `Fallback: ${dimension.default_from || dimension.default}`; summary.append(fallbackLine);
        }
        const actions = document.createElement('div'); actions.className = 'calculated-dimension-actions';
        const editButton = document.createElement('button'); editButton.type = 'button'; editButton.textContent = '✎'; editButton.title = `Edit ${dimension.name}`;
        const duplicate = document.createElement('button'); duplicate.type = 'button'; duplicate.className = 'auto-calculated-field-duplicate'; duplicate.textContent = '⧉'; duplicate.title = `Duplicate ${dimension.name}`;
        const exportLink = document.createElement('a'); exportLink.className = 'ghost-link icon-action auto-calculated-field-export'; exportLink.textContent = '↓'; exportLink.title = `Export ${dimension.name}`; exportLink.href = `/workspace/calculated-dimensions/export?${new URLSearchParams({name: dimension.name})}`;
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'danger-button auto-calculated-field-remove'; remove.textContent = '−'; remove.title = `Delete ${dimension.name}`;
        editButton.addEventListener('click', () => edit(index));
        duplicate.addEventListener('click', async () => {
          const names = new Set(dimensions.map((item) => String(item.name || '').toLocaleLowerCase()));
          let copyName = `${dimension.name} Copy`; let suffix = 2;
          while (names.has(copyName.toLocaleLowerCase())) copyName = `${dimension.name} Copy ${suffix++}`;
          const copy = JSON.parse(JSON.stringify({...dimension, name: copyName}));
          dimensions = [...dimensions.slice(0, index + 1), copy, ...dimensions.slice(index + 1)];
          render();
          updateSaveActions();
        });
        remove.addEventListener('click', async () => {
          if (!await showConfirmDialog(`Delete auto-calculated field '${dimension.name}'? The deletion will remain in memory until you save.`, {title: 'Delete Auto-calculated Field', confirmLabel: 'Delete', tone: 'danger'})) return;
          const deletedName = String(dimension.name || '').toLocaleLowerCase();
          dimensions = dimensions.filter((_item, itemIndex) => itemIndex !== index);
          for (const [from, to] of pendingRenames) {
            if (String(to).toLocaleLowerCase() === deletedName) pendingRenames.delete(from);
          }
          render();
          updateSaveActions();
        });
        actions.append(editButton, duplicate, exportLink, remove); item.append(orderActions, identity, summary, actions); list.append(item);
      });
      if (!dimensions.length) { const empty = document.createElement('p'); empty.className = 'form-note'; empty.textContent = 'This workspace has no auto-calculated fields.'; list.append(empty); }
    };
    const persistChanges = async (materialize) => {
      if (!hasPendingChanges()) return;
      const action = materialize ? saveAndMaterialize : save;
      const originalLabel = action.textContent;
      try {
        save.disabled = true; saveAndMaterialize.disabled = true;
        action.setAttribute('aria-busy', 'true'); action.textContent = 'Saving…';
        showLoadingOverlay(
          materialize ? 'Saving and Materializing Auto-calculated Fields' : 'Saving Auto-calculated Fields',
          materialize ? 'Saving the applied changes. Materialization will continue in the background.' : 'Saving the applied changes without starting materialization.',
        );
        await saveDimensions(dimensions, Array.from(pendingRenames, ([from, to]) => ({from, to})), materialize, false);
        persistedDimensions = JSON.parse(JSON.stringify(dimensions));
        pendingRenames.clear();
        hideLoadingOverlay();
        updateSaveActions();
        finish();
      } catch (error) {
        hideLoadingOverlay();
        updateSaveActions();
        showInfoDialog(error.message || 'Unable to save auto-calculated fields.', {title: 'Auto-calculated Fields', tone: 'error'});
      } finally {
        action.removeAttribute('aria-busy'); action.textContent = originalLabel;
      }
    };
    save.addEventListener('click', () => { void persistChanges(false); });
    saveAndMaterialize.addEventListener('click', () => { void persistChanges(true); });
    add.addEventListener('click', () => edit()); render(); updateSaveActions(); close.focus();
  });
});

function limitSeriesCollectionByX(seriesCollection, xMaxOverride) {
  if (!Number.isFinite(Number(xMaxOverride))) return seriesCollection;
  return seriesCollection
    .map((item) => {
      const filteredLabels = [];
      const filteredSeries = [];
      (item.labels || []).forEach((label, index) => {
        if (Number(label) <= Number(xMaxOverride)) {
          filteredLabels.push(label);
          filteredSeries.push((item.series || [])[index]);
        }
      });
      return {...item, labels: filteredLabels, series: filteredSeries};
    })
    .filter((item) => item.labels.length > 0 && item.series.length > 0);
}

// Card-shaped tables are much easier to scan on a compact phone when their
// rows are bounded. The pager is deliberately client-side: each source table
// keeps its existing server/API pagination and this only controls the mobile
// card presentation of the rows already available to the page.
(() => {
  const selector = [
    'table.queue-table', 'table.users-table', 'table.catalogue-workspace-table',
    'table.report-jobs-table', 'table.workspace-library-table', 'table.recovered-transfer-table',
    'table.app-logs-table', 'table.admin-datasets-table', 'table.database-editor-table',
    'table.operator-mappings-table', 'table.ds-dashboards-table',
    '.report-charts-grid', '.workspace-calculated-dimensions-list',
  ].join(', ');
  const compactViewport = window.matchMedia('(max-width: 640px)');
  const pageSize = 1;
  const states = new WeakMap();
  let scheduled = false;

  const cardRows = (collection) => {
    if (collection.matches('.report-charts-grid')) {
      return Array.from(collection.querySelectorAll(':scope > .report-chart-card'))
        .filter((card) => !card.hidden && !card.hasAttribute('data-mobile-card-pagination-ignore'));
    }
    if (collection.matches('.workspace-calculated-dimensions-list')) {
      return Array.from(collection.querySelectorAll(':scope > .workspace-calculated-dimension-row'))
        .filter((row) => !row.hidden);
    }
    return Array.from(collection.tBodies)
      .flatMap((body) => Array.from(body.rows))
      .filter((row) => !row.hidden
        && !row.classList.contains('database-empty-row')
        && !row.hasAttribute('data-app-log-no-results')
        && !row.hasAttribute('data-mobile-card-pagination-ignore'));
  };

  const refreshTable = (table) => {
    let state = states.get(table);
    if (!state) {
      const pager = document.createElement('nav');
      pager.className = 'mobile-card-pagination';
      pager.hidden = true;
      pager.setAttribute('aria-label', table.matches('.report-charts-grid') ? 'Chart pages' : (table.matches('.workspace-calculated-dimensions-list') ? 'Auto-calculated Fields pages' : 'Card pages'));
      pager.innerHTML = '<button type="button" data-mobile-card-first aria-label="First page" title="First page">⏮</button><button type="button" data-mobile-card-previous aria-label="Previous page" title="Previous page">⬅</button><span data-mobile-card-page-label>Page 1 of 1</span><button type="button" data-mobile-card-next aria-label="Next page" title="Next page">➡</button><button type="button" data-mobile-card-last aria-label="Last page" title="Last page">⏭</button>';
      const placeAfter = table.closest('.table-wrap, .data-table-wrap, .queue-table-wrap, .database-editor-wrap, .catalogue-workspace-table-wrap') || table;
      placeAfter.insertAdjacentElement('afterend', pager);
      state = {page: 0, pager};
      states.set(table, state);
      pager.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button) return;
        const rows = cardRows(table);
        const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
        if (button.hasAttribute('data-mobile-card-first')) state.page = 0;
        if (button.hasAttribute('data-mobile-card-previous')) state.page = Math.max(0, state.page - 1);
        if (button.hasAttribute('data-mobile-card-next')) state.page = Math.min(pageCount - 1, state.page + 1);
        if (button.hasAttribute('data-mobile-card-last')) state.page = pageCount - 1;
        refreshTable(table);
      });
    }
    const rows = cardRows(table);
    if (!compactViewport.matches) {
      rows.forEach((row) => row.classList.remove('mobile-card-page-hidden'));
      state.pager.hidden = true;
      return;
    }
    const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
    state.page = Math.min(state.page, pageCount - 1);
    rows.forEach((row, index) => row.classList.toggle('mobile-card-page-hidden', Math.floor(index / pageSize) !== state.page));
    state.pager.hidden = rows.length <= pageSize;
    state.pager.querySelector('[data-mobile-card-page-label]').textContent = `Page ${state.page + 1} of ${pageCount}`;
    state.pager.querySelector('[data-mobile-card-first]').disabled = state.page === 0;
    state.pager.querySelector('[data-mobile-card-previous]').disabled = state.page === 0;
    state.pager.querySelector('[data-mobile-card-next]').disabled = state.page >= pageCount - 1;
    state.pager.querySelector('[data-mobile-card-last]').disabled = state.page >= pageCount - 1;
  };

  const refreshAll = () => document.querySelectorAll(selector).forEach(refreshTable);
  document.addEventListener('mobile-card-pagination:refresh', (event) => {
    const source = event.target;
    if (!(source instanceof Element)) return;
    const collection = source.closest(selector);
    if (!collection) return;
    const state = states.get(collection);
    if (event.detail?.reset && state) state.page = 0;
    refreshTable(collection);
  });
  const scheduleRefresh = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(() => { scheduled = false; refreshAll(); });
  };
  compactViewport.addEventListener('change', scheduleRefresh);
  new MutationObserver((mutations) => {
    if (mutations.some((mutation) => mutation.type === 'childList' || mutation.attributeName === 'hidden')) scheduleRefresh();
  }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['hidden']});
  refreshAll();
})();

function drawLineChart(svg, labels, series, width, height, padding, axisLabels = {}, xMaxOverride = null, xMinOverride = null) {
  const palette = ['#0b7a75', '#dd653e', '#245a96', '#b84d3a', '#6d46a8', '#228a5d', '#c78b1d', '#4d6a88'];
  const rawSeriesCollection = Array.isArray(series) && series.length > 0 && typeof series[0] === 'object' && Array.isArray(series[0].series)
    ? series
    : [{name: 'CDF', labels, series}];
  const seriesCollection = limitSeriesCollectionByX(rawSeriesCollection, xMaxOverride);
  if (seriesCollection.length === 0) {
    svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#526371">No chart data available</text>';
    return;
  }
  const flatLabels = seriesCollection.flatMap((item) => item.labels || []);
  const flatSeries = seriesCollection.flatMap((item) => item.series || []);
  const dataMinX = Math.min(...flatLabels);
  const dataMaxX = Math.max(...flatLabels);
  const minX = Number.isFinite(Number(xMinOverride)) ? Number(xMinOverride) : dataMinX;
  const maxX = Number.isFinite(Number(xMaxOverride)) ? Number(xMaxOverride) : dataMaxX;
  const maxY = Math.max(...flatSeries, 1);
  const legendHeight = seriesCollection.length > 1 ? 28 : 0;
  const xAxisLabel = String(axisLabels.x || 'Metric value');
  const yAxisLabel = String(axisLabels.y || 'Cumulative probability');
  const leftPadding = padding + 26;
  const rightPadding = padding;
  const bottomPadding = padding + 30;
  const innerTop = padding + legendHeight;
  const innerWidth = width - leftPadding - rightPadding;
  const innerHeight = height - bottomPadding - innerTop;
  const domainMinX = Math.min(minX, maxX);
  const domainMaxX = Math.max(minX, maxX);
  const scaleX = (value) => leftPadding + ((value - domainMinX) / ((domainMaxX - domainMinX) || 1)) * innerWidth;
  const scaleY = (value) => height - bottomPadding - (value / maxY) * innerHeight;
  const xTicks = [domainMinX, (domainMinX + domainMaxX) / 2, domainMaxX];
  const yTicks = [0, 0.5, 1.0];
  const xTickLabels = xTicks.map((value) => `
    <line x1="${scaleX(value)}" y1="${height - bottomPadding}" x2="${scaleX(value)}" y2="${height - bottomPadding + 6}" stroke="#9ab0bc" />
    <text x="${scaleX(value)}" y="${height - bottomPadding + 18}" text-anchor="middle" fill="#526371" font-size="11">${formatAxisValue(value)}</text>
  `).join('');
  const yTickLabels = yTicks.map((value) => `
    <line x1="${leftPadding - 6}" y1="${scaleY(value)}" x2="${leftPadding}" y2="${scaleY(value)}" stroke="#9ab0bc" />
    <text x="${leftPadding - 10}" y="${scaleY(value) + 4}" text-anchor="end" fill="#526371" font-size="11">${formatAxisValue(value)}</text>
  `).join('');
  const lines = seriesCollection.map((item, index) => {
    const color = item.color || palette[index % palette.length];
    const points = (item.labels || []).map((label, pointIndex) => `${scaleX(label)},${scaleY((item.series || [])[pointIndex])}`).join(' ');
    return `<polyline fill="none" stroke="${color}" stroke-width="3" points="${points}" />`;
  }).join('');
  const legend = seriesCollection.length > 1
    ? seriesCollection.map((item, index) => {
        const color = item.color || palette[index % palette.length];
        const x = padding + (index % 3) * 170;
        const y = 18 + Math.floor(index / 3) * 18;
        return `
          <circle cx="${x}" cy="${y}" r="5" fill="${color}"></circle>
          <text x="${x + 10}" y="${y + 4}" fill="#526371" font-size="11">${String(item.name).slice(0, 20)}</text>
        `;
      }).join('')
    : `<text x="${padding}" y="18" fill="#526371">CDF</text>`;
  svg.innerHTML = `
    <line x1="${leftPadding}" y1="${height - bottomPadding}" x2="${width - rightPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    <line x1="${leftPadding}" y1="${innerTop}" x2="${leftPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    ${xTickLabels}
    ${yTickLabels}
    ${legend}
    ${lines}
    <text x="${leftPadding + innerWidth / 2}" y="${height - 4}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600">${xAxisLabel}</text>
    <text x="16" y="${innerTop + innerHeight / 2}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600" transform="rotate(-90 16 ${innerTop + innerHeight / 2})">${yAxisLabel}</text>
  `;
}

function drawBarChart(svg, labels, series, width, height, padding, axisLabels = {}, colors = []) {
  const numericSeries = series.map((value) => Number(value)).filter((value) => Number.isFinite(value));
  const maxValue = numericSeries.length > 0 ? Math.max(...numericSeries) : 1;
  const yAxisLabel = String(axisLabels.y || 'Mean metric');
  const leftPadding = padding + 26;
  const bottomPadding = padding + 18;
  const topPadding = padding;
  const innerWidth = width - leftPadding - padding;
  const innerHeight = height - topPadding - bottomPadding;
  const barWidth = innerWidth / labels.length;
  const bars = labels.map((label, index) => {
    const value = series[index];
    const scaledHeight = ((Number(value) || 0) / (maxValue || 1)) * innerHeight;
    const x = leftPadding + index * barWidth + 8;
    const y = height - bottomPadding - scaledHeight;
    const textX = x + Math.max(barWidth - 16, 24) / 2;
    const valueLabel = Number.isFinite(Number(value)) ? Number(value).toFixed(Math.abs(Number(value)) >= 100 ? 0 : 2).replace(/\.00$/, '') : String(value);
    const valueY = scaledHeight > 28 ? y + 18 : Math.max(y - 8, topPadding + 12);
    const valueFill = scaledHeight > 28 ? 'rgba(255,255,255,0.96)' : '#334550';
    return `
      <rect x="${x}" y="${y}" width="${Math.max(barWidth - 16, 24)}" height="${scaledHeight}" rx="10" fill="${colors[index] || '#dd653e'}"></rect>
      <text x="${textX}" y="${valueY}" text-anchor="middle" fill="${valueFill}" font-size="11" font-weight="700">${valueLabel}</text>
      <text x="${textX}" y="${height - 10}" text-anchor="middle" fill="#526371" font-size="11">${String(label).slice(0, 12)}</text>
    `;
  }).join('');
  svg.innerHTML = `
    <line x1="${leftPadding}" y1="${height - bottomPadding}" x2="${width - padding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    <line x1="${leftPadding}" y1="${topPadding}" x2="${leftPadding}" y2="${height - bottomPadding}" stroke="#9ab0bc" />
    ${bars}
    <text x="16" y="${topPadding + innerHeight / 2}" text-anchor="middle" fill="#526371" font-size="12" font-weight="600" transform="rotate(-90 16 ${topPadding + innerHeight / 2})">${yAxisLabel}</text>
  `;
}

function drawChart(container) {
  const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[],"type":"line"}');
  const svg = container.querySelector('.chart-svg');
  const labels = payload.labels || [];
  const series = payload.series || [];
  const seriesCollection = payload.series_collection || [];
  const hasLineData = (labels.length > 0 && series.length > 0) || seriesCollection.length > 0;
  if (!svg || (payload.type === 'line' ? !hasLineData : (labels.length === 0 || series.length === 0))) {
    if (svg) {
      svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#526371">No chart data available</text>';
    }
    return;
  }
  const width = 600;
  const isCdfChart = container.dataset.chartKind === 'cdf';
  const height = isCdfChart ? 280 : Math.max(Math.round(svg.getBoundingClientRect().height || 280), 280);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const padding = 34;
  if (payload.type === 'bar') {
    drawBarChart(svg, labels, series, width, height, padding, {y: payload.y_axis_label}, payload.colors || []);
    return;
  }
  const activeXMax = Number(container.dataset.cdfXMax || payload.x_view_max_default || payload.x_max);
  drawLineChart(
    svg,
    labels,
    seriesCollection.length > 0 ? seriesCollection : series,
    width,
    height,
    padding,
    {x: payload.x_axis_label, y: payload.y_axis_label},
    activeXMax,
    0,
  );
}

function setupCdfRangeControls() {
  document.querySelectorAll('.chart-card[data-chart-kind="cdf"]').forEach((container) => {
    const payload = JSON.parse(container.dataset.chart || '{"labels":[],"series":[],"type":"line"}');
    const control = container.querySelector('[data-cdf-range-control]');
    const slider = container.querySelector('[data-cdf-range-slider]');
    const valueNode = container.querySelector('[data-cdf-range-value]');
    const xMin = Number(payload.x_min);
    const xMax = Number(payload.x_max);
    const defaultXMax = Number(payload.x_view_max_default);
    const recommendedXMax = Number(payload.x_view_max_recommended);

    if (!control || !slider || !Number.isFinite(xMin) || !Number.isFinite(xMax) || xMax <= xMin) {
      if (control) control.hidden = true;
      return;
    }

    slider.min = String(xMin);
    slider.max = String(xMax);
    slider.step = String(Math.max((xMax - xMin) / 400, 0.0001));
    slider.value = String(Number.isFinite(defaultXMax) ? defaultXMax : xMax);
    container.dataset.cdfXMax = slider.value;

    const updateRangeUi = () => {
      const currentValue = Number(slider.value);
      container.dataset.cdfXMax = String(currentValue);
      if (valueNode) {
        valueNode.textContent = `${formatAxisValue(xMin)} -> ${formatAxisValue(currentValue)}`;
      }
      drawChart(container);
    };

    control.hidden = false;
    slider.addEventListener('input', updateRangeUi);
    slider.addEventListener('change', updateRangeUi);
    updateRangeUi();
  });
}

document.querySelectorAll('[data-chart]').forEach(drawChart);
setupCdfRangeControls();

document.querySelectorAll('[data-horizontal-wheel-scroll]').forEach((container) => {
  container.addEventListener('wheel', (event) => {
    if (!event.shiftKey || container.scrollWidth <= container.clientWidth) return;
    event.preventDefault();
    container.scrollLeft += event.deltaY || event.deltaX;
  }, {passive: false});
});

const initializeServerDatasetPreview = (toolbar) => {
  const panel = toolbar.closest('.dataset-preview-panel');
  const table = panel?.querySelector('[data-server-preview-table]');
  const tbody = table?.querySelector('tbody');
  const headers = Array.from(table?.querySelectorAll('thead th') || []);
  const clearFilters = panel?.querySelector('[data-preview-clear-filters]');
  const clearFiltersLabel = clearFilters?.querySelector('[data-preview-clear-label]');
  const filterStatus = panel?.querySelector('[data-preview-filter-status]');
  const filteringStatus = document.querySelector('[data-preview-filtering-status]');
  const filteringStatusText = filteringStatus?.querySelector('[data-preview-filtering-text]');
  const columnSearch = toolbar.querySelector('[data-server-preview-column-search]');
  const exportButton = toolbar.querySelector('[data-server-preview-export]');
  const tagFilter = toolbar.querySelector('[data-preview-tag-filter]');
  const tagFilterToggle = tagFilter?.querySelector('[data-preview-tag-filter-toggle]');
  const tagFilterLabel = tagFilterToggle?.querySelector('[data-preview-tag-filter-label]');
  const tagFilterMenu = tagFilter?.querySelector('[data-preview-tag-filter-menu]');
  const tagFilterAll = tagFilterMenu?.querySelector('[data-preview-tag-filter-all]');
  const tagItems = Array.from(panel?.querySelectorAll('[data-preview-column-tag-item]') || []);
  const tagStrip = panel?.querySelector('[data-preview-column-tag-strip]');
  const tableWrap = panel?.querySelector('.dataset-preview-table-wrap');
  const rowPill = panel?.querySelector('[data-preview-row-pill]');
  const pageStatus = panel?.querySelector('[data-preview-page-status]');
  const firstPage = panel?.querySelector('[data-preview-first-page]');
  const previousPage = panel?.querySelector('[data-preview-previous-page]');
  const nextPage = panel?.querySelector('[data-preview-next-page]');
  const lastPage = panel?.querySelector('[data-preview-last-page]');
  if (!table || !tbody || !headers.length || !clearFilters) return;

  const endpoint = toolbar.dataset.endpoint;
  const pageSize = Number(toolbar.dataset.pageSize || 100);
  const columnFilters = new Map();
  toolbar.previewColumnFilters = () => Object.fromEntries(
    Array.from(columnFilters, ([column, values]) => [column, Array.from(values)]),
  );
  const selectedTags = new Set();
  let currentPage = 0;
  let filteredTotal = Number(toolbar.dataset.totalRows || 0);
  let unfilteredTotal = filteredTotal;
  let openColumnMenu = null;
  let requestSequence = 0;
  const formatRowCount = value => new Intl.NumberFormat('en-US').format(Number(value) || 0);
  const termsFor = (value) => String(value || '').split(',').map((term) => term.trim().toLocaleLowerCase()).filter(Boolean);

  const applyColumnSearch = () => {
    const terms = termsFor(columnSearch?.value);
    headers.forEach((header, index) => {
      const label = (header.dataset.columnLabel || header.dataset.columnName || '').toLocaleLowerCase();
      const matchesName = !terms.length || terms.some((term) => label.includes(term));
      const matchesTag = !selectedTags.size || Array.from(selectedTags).some((tag) => (
        tag === (header.dataset.columnKind || '')
        || (tag === 'PINNED' && header.dataset.columnPinned === 'true')
        || (tag === 'UN_PINNED' && header.dataset.columnPinned !== 'true')
      ));
      const visible = matchesName && matchesTag;
      header.hidden = !visible;
      if (tagItems[index]) tagItems[index].hidden = !visible;
      Array.from(tbody.rows).forEach((row) => {
        if (row.cells[index]) row.cells[index].hidden = !visible;
      });
    });
    updateControls(tbody.rows.length);
    requestAnimationFrame(() => requestAnimationFrame(syncTagStrip));
  };

  const syncTagStrip = () => {
    if (!tagStrip || !tableWrap) return;
    tagItems.forEach((item) => { item.style.width = ''; });
    tagStrip.style.width = `${table.scrollWidth}px`;
    headers.forEach((header, index) => {
      if (tagItems[index]) tagItems[index].style.width = `${header.getBoundingClientRect().width}px`;
    });
    tagStrip.style.transform = `translateX(${-tableWrap.scrollLeft}px)`;
  };

  const closeColumnMenu = () => {
    if (!openColumnMenu) return;
    openColumnMenu.trigger.setAttribute('aria-expanded', 'false');
    openColumnMenu.menu.remove();
    openColumnMenu = null;
  };

  const updateControls = (rowCount) => {
    const activeFilters = columnFilters.size;
    if (clearFiltersLabel) clearFiltersLabel.textContent = `Clear ${activeFilters} Filter${activeFilters === 1 ? '' : 's'}`;
    clearFilters.disabled = activeFilters === 0;
    const totalPages = Math.max(1, Math.ceil(filteredTotal / pageSize));
    const start = filteredTotal ? currentPage * pageSize + 1 : 0;
    const end = filteredTotal ? start + rowCount - 1 : 0;
    if (filterStatus) {
      const rowSummary = activeFilters
        ? `Showing ${formatRowCount(start)}-${formatRowCount(end)} of ${formatRowCount(filteredTotal)} matching rows (${formatRowCount(unfilteredTotal)} total)`
        : `Showing ${formatRowCount(start)}-${formatRowCount(end)} of ${formatRowCount(unfilteredTotal)} rows`;
      const visibleColumns = headers.filter((header) => !header.hidden).length;
      filterStatus.textContent = `${rowSummary} · ${formatRowCount(visibleColumns)} of ${formatRowCount(headers.length)} columns`;
    }
    if (rowPill) rowPill.textContent = `${formatRowCount(rowCount)} rows shown`;
    if (pageStatus) pageStatus.textContent = `Page ${currentPage + 1} of ${totalPages}`;
    if (firstPage) firstPage.disabled = currentPage === 0;
    if (previousPage) previousPage.disabled = currentPage === 0;
    if (nextPage) nextPage.disabled = currentPage >= totalPages - 1;
    if (lastPage) lastPage.disabled = currentPage >= totalPages - 1;
    headers.forEach((header) => header.classList.toggle('has-value-filter', columnFilters.has(header.dataset.columnName)));
  };

  const setLoading = (loading, message = 'Loading dataset…') => {
    toolbar.setAttribute('aria-busy', String(loading));
    if (filteringStatusText) filteringStatusText.textContent = message;
    if (filteringStatus) filteringStatus.hidden = !loading;
    [firstPage, previousPage, nextPage, lastPage].forEach((button) => {
      if (button && loading) button.disabled = true;
    });
  };

  const requestPreview = async (page, filterColumn = null) => {
    if (typeof toolbar.previewRequest === 'function') {
      return toolbar.previewRequest({
        page,
        column_filters: Object.fromEntries(Array.from(columnFilters, ([column, values]) => [column, Array.from(values)])),
        filter_column: filterColumn,
      });
    }
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({
        page,
        column_filters: Object.fromEntries(Array.from(columnFilters, ([column, values]) => [column, Array.from(values)])),
        filter_column: filterColumn,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Unable to load the dataset preview.');
    return payload;
  };

  const exportPreview = async () => {
    if (!exportButton || !endpoint || exportButton.disabled) return;
    exportButton.disabled = true;
    showLoadingOverlay('Exporting Dataset', 'Please wait while the filtered rows are written to CSV.');
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        body: JSON.stringify({
          column_filters: Object.fromEntries(Array.from(columnFilters, ([column, values]) => [column, Array.from(values)])),
          download: true,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Unable to export the dataset preview.');
      }
      const disposition = response.headers.get('content-disposition') || '';
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'dataset-preview.csv';
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = filename;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      showInfoDialog(error.message || 'Unable to export the dataset preview.', {title: 'Export CSV', tone: 'error'});
    } finally {
      hideLoadingOverlay();
      exportButton.disabled = false;
    }
  };

  const renderRows = (rows) => {
    tbody.replaceChildren();
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      headers.forEach((header) => {
        const td = document.createElement('td');
        td.textContent = row[header.dataset.columnName] ?? '';
        ['gcid-column', 'vendor-column', 'derived-cdr-column', 'analysis-derived-cdr-column', 'main-cdr-column', 'auto-calculated-preview-column'].forEach((className) => {
          if (header.classList.contains(className)) td.classList.add(className);
        });
        tr.append(td);
      });
      tbody.append(tr);
    });
    applyColumnSearch();
  };

  const loadPage = async (page, message = 'Loading dataset…') => {
    const sequence = ++requestSequence;
    const horizontalPosition = (() => {
      if (!tableWrap) return {scrollLeft: 0, columnName: '', inset: 0};
      const viewportLeft = tableWrap.getBoundingClientRect().left;
      const anchor = headers.find((header) => !header.hidden && header.getBoundingClientRect().right > viewportLeft);
      return {
        scrollLeft: tableWrap.scrollLeft,
        columnName: anchor?.dataset.columnName || '',
        inset: anchor ? Math.max(0, viewportLeft - anchor.getBoundingClientRect().left) : 0,
      };
    })();
    setLoading(true, message);
    closeColumnMenu();
    try {
      const payload = await requestPreview(page);
      if (sequence !== requestSequence) return;
      currentPage = Number(payload.page || 0);
      filteredTotal = Number(payload.total || 0);
      unfilteredTotal = Number(payload.unfiltered_total || 0);
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      renderRows(rows);
      updateControls(rows.length);
      const restoreHorizontalOffset = () => {
        if (sequence !== requestSequence || !tableWrap) return;
        const anchor = horizontalPosition.columnName
          ? headers.find((header) => header.dataset.columnName === horizontalPosition.columnName)
          : null;
        if (anchor && !anchor.hidden) {
          const viewportLeft = tableWrap.getBoundingClientRect().left;
          const anchorContentLeft = anchor.getBoundingClientRect().left - viewportLeft + tableWrap.scrollLeft;
          tableWrap.scrollLeft = anchorContentLeft + horizontalPosition.inset;
        } else {
          tableWrap.scrollLeft = horizontalPosition.scrollLeft;
        }
        syncTagStrip();
      };
      restoreHorizontalOffset();
      requestAnimationFrame(() => requestAnimationFrame(restoreHorizontalOffset));
    } catch (error) {
      showInfoDialog(error.message || 'Unable to load the dataset preview.', {title: 'Dataset preview', tone: 'error'});
      updateControls(tbody.rows.length);
    } finally {
      if (sequence === requestSequence) setLoading(false);
    }
  };

  const positionMenu = (menu, trigger) => {
    const bounds = trigger.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 20);
    menu.style.width = `${width}px`;
    menu.style.left = `${Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10))}px`;
    const preferredTop = bounds.bottom + 5;
    const menuHeight = menu.offsetHeight;
    menu.style.top = `${preferredTop + menuHeight <= window.innerHeight - 10 ? preferredTop : Math.max(10, bounds.top - menuHeight - 5)}px`;
  };

  const openValueMenu = async (header, trigger) => {
    if (openColumnMenu?.trigger === trigger) {
      closeColumnMenu();
      return;
    }
    closeColumnMenu();
    const column = header.dataset.columnName;
    const menu = document.createElement('section');
    menu.className = 'preview-column-filter-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filter ${column}`);
    menu.textContent = 'Loading values...';
    document.body.append(menu);
    trigger.setAttribute('aria-expanded', 'true');
    openColumnMenu = {menu, trigger};
    positionMenu(menu, trigger);
    try {
      const payload = await requestPreview(currentPage, column);
      if (openColumnMenu?.menu !== menu) return;
      const values = Array.isArray(payload.filter_values) ? payload.filter_values.map(String) : [];
      const activeValues = columnFilters.get(column);
      const selectedValues = new Set(activeValues ? Array.from(activeValues) : values);
      const search = document.createElement('input');
      search.type = 'search';
      search.className = 'preview-column-filter-search';
      search.placeholder = 'Search values';
      search.autocomplete = 'off';
      search.setAttribute('aria-label', `Search ${column} values`);
      const toolbarNode = document.createElement('div');
      toolbarNode.className = 'preview-column-filter-toolbar';
      const selectAllNone = document.createElement('button');
      selectAllNone.type = 'button';
      selectAllNone.textContent = 'Select All/None';
      toolbarNode.append(selectAllNone);
      const options = document.createElement('div');
      options.className = 'preview-column-filter-options';
      values.forEach((value) => {
        const option = document.createElement('label');
        option.className = 'preview-column-filter-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = value;
        checkbox.checked = selectedValues.has(value);
        checkbox.setAttribute('data-preview-value-option', '');
        const caption = document.createElement('span');
        caption.textContent = value || '(Blank)';
        option.append(checkbox, caption);
        options.append(option);
      });
      const footer = document.createElement('div');
      footer.className = 'preview-column-filter-footer';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'preview-column-filter-cancel';
      cancel.textContent = 'Cancel';
      const apply = document.createElement('button');
      apply.type = 'button';
      apply.className = 'preview-column-filter-apply';
      apply.textContent = 'Apply';
      footer.append(cancel, apply);
      menu.replaceChildren(search, toolbarNode, options, footer);
      positionMenu(menu, trigger);
      search.addEventListener('input', () => {
        const term = search.value.trim().toLocaleLowerCase();
        options.querySelectorAll('.preview-column-filter-option').forEach((option) => {
          option.hidden = Boolean(term) && !option.textContent.toLocaleLowerCase().includes(term);
        });
      });
      selectAllNone.addEventListener('click', () => {
        const visible = Array.from(options.querySelectorAll('.preview-column-filter-option:not([hidden]) input'));
        const shouldSelect = visible.some((checkbox) => !checkbox.checked);
        visible.forEach((checkbox) => { checkbox.checked = shouldSelect; });
      });
      cancel.addEventListener('click', closeColumnMenu);
      apply.addEventListener('click', () => {
        const accepted = new Set(Array.from(options.querySelectorAll('[data-preview-value-option]:checked')).map((checkbox) => checkbox.value));
        if (accepted.size === values.length) columnFilters.delete(column);
        else columnFilters.set(column, accepted);
        closeColumnMenu();
        loadPage(0, 'Filtering dataset…');
      });
      menu.addEventListener('click', (event) => event.stopPropagation());
      requestAnimationFrame(() => search.focus());
    } catch (error) {
      closeColumnMenu();
      showInfoDialog(error.message || 'Unable to load column values.', {title: 'Dataset preview', tone: 'error'});
    }
  };

  headers.forEach((header) => {
    const columnLabel = header.dataset.columnLabel || header.dataset.columnName || header.textContent.trim();
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'preview-column-filter-trigger';
    trigger.dataset.columnLabel = columnLabel;
    trigger.setAttribute('aria-label', `Filter ${columnLabel}`);
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    const caption = document.createElement('span');
    caption.textContent = columnLabel;
    const icon = document.createElement('span');
    icon.className = 'preview-column-filter-icon';
    icon.textContent = '▾';
    icon.setAttribute('aria-hidden', 'true');
    trigger.append(caption, icon);
    header.replaceChildren(trigger);
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      openValueMenu(header, trigger);
    });
  });

  clearFilters.addEventListener('click', () => {
    columnFilters.clear();
    loadPage(0, 'Clearing dataset filters…');
  });
  exportButton?.addEventListener('click', exportPreview);
  columnSearch?.addEventListener('input', applyColumnSearch);
  tagFilterToggle?.addEventListener('click', (event) => {
    event.stopPropagation();
    const opening = tagFilterMenu?.hidden ?? true;
    if (tagFilterMenu) tagFilterMenu.hidden = !opening;
    tagFilterToggle.setAttribute('aria-expanded', String(opening));
  });
  tagFilterMenu?.addEventListener('click', (event) => event.stopPropagation());
  tagFilterAll?.addEventListener('click', () => {
    selectedTags.clear();
    tagFilterMenu?.querySelectorAll('input').forEach((checkbox) => { checkbox.checked = false; });
    if (tagFilterLabel) tagFilterLabel.textContent = 'All Labels';
    applyColumnSearch();
    if (tagFilterMenu) tagFilterMenu.hidden = true;
    tagFilterToggle?.setAttribute('aria-expanded', 'false');
  });
  tagFilterMenu?.querySelectorAll('input').forEach((checkbox) => checkbox.addEventListener('change', () => {
    if (checkbox.checked) selectedTags.add(checkbox.value); else selectedTags.delete(checkbox.value);
    if (tagFilterLabel) tagFilterLabel.textContent = selectedTags.size ? `${selectedTags.size} Label${selectedTags.size === 1 ? '' : 's'}` : 'All Labels';
    applyColumnSearch();
    requestAnimationFrame(syncTagStrip);
  }));
  firstPage?.addEventListener('click', () => loadPage(0));
  previousPage?.addEventListener('click', () => loadPage(Math.max(0, currentPage - 1)));
  nextPage?.addEventListener('click', () => loadPage(currentPage + 1));
  lastPage?.addEventListener('click', () => loadPage(Math.max(0, Math.ceil(filteredTotal / pageSize) - 1)));
  const closePreviewMenus = () => {
    closeColumnMenu();
    if (tagFilterMenu) tagFilterMenu.hidden = true;
    tagFilterToggle?.setAttribute('aria-expanded', 'false');
  };
  const closePreviewMenuOnEscape = (event) => { if (event.key === 'Escape') closeColumnMenu(); };
  const syncTagsAfterScroll = () => { closeColumnMenu(); syncTagStrip(); };
  document.addEventListener('click', closePreviewMenus);
  document.addEventListener('keydown', closePreviewMenuOnEscape);
  window.addEventListener('resize', closeColumnMenu);
  tableWrap?.addEventListener('scroll', syncTagsAfterScroll, {passive: true});
  window.addEventListener('resize', syncTagStrip);
  updateControls(tbody.rows.length);
  applyColumnSearch();
  requestAnimationFrame(syncTagStrip);
  return () => {
    requestSequence += 1;
    closeColumnMenu();
    document.removeEventListener('click', closePreviewMenus);
    document.removeEventListener('keydown', closePreviewMenuOnEscape);
    exportButton?.removeEventListener('click', exportPreview);
    window.removeEventListener('resize', closeColumnMenu);
    tableWrap?.removeEventListener('scroll', syncTagsAfterScroll);
    window.removeEventListener('resize', syncTagStrip);
  };
};

document.querySelectorAll('[data-server-dataset-preview]').forEach(initializeServerDatasetPreview);

window.createUnifiedDatasetViewer = ({host, payload, requestPage, exportControl = null, exportRequest = null}) => {
  if (!(host instanceof HTMLElement) || !payload || typeof requestPage !== 'function') return null;
  if (typeof host.unifiedDatasetViewerDestroy === 'function') host.unifiedDatasetViewerDestroy();
  const columns = Array.isArray(payload.columns) ? payload.columns.map(String) : [];
  const metadata = payload.column_metadata && typeof payload.column_metadata === 'object'
    ? payload.column_metadata : {};
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const viewer = element('section', 'dataset-preview-panel unified-dataset-viewer');
  const toolbar = element('div', 'preview-server-toolbar');
  toolbar.setAttribute('data-server-dataset-preview', '');
  toolbar.dataset.pageSize = String(payload.page_size || 100);
  toolbar.dataset.totalRows = String(payload.unfiltered_total ?? payload.chart_total ?? payload.total ?? 0);
  const searchLabel = element('label', 'preview-server-column-search', 'Search columns');
  const search = element('input');
  search.type = 'search'; search.placeholder = 'Column names, separated by commas'; search.autocomplete = 'off';
  search.setAttribute('data-server-preview-column-search', ''); searchLabel.append(search);
  const tagFilter = element('div', 'preview-tag-filter'); tagFilter.setAttribute('data-preview-tag-filter', '');
  tagFilter.append(element('span', '', 'Filter labels'));
  const tagToggle = element('button'); tagToggle.type = 'button'; tagToggle.setAttribute('data-preview-tag-filter-toggle', ''); tagToggle.setAttribute('aria-expanded', 'false');
  const tagLabel = element('span', '', 'All Labels'); tagLabel.setAttribute('data-preview-tag-filter-label', '');
  tagToggle.append(tagLabel);
  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); arrow.setAttribute('viewBox', '0 0 20 20'); arrow.setAttribute('aria-hidden', 'true');
  const arrowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path'); arrowPath.setAttribute('d', 'm5 7 5 6 5-6'); arrow.append(arrowPath); tagToggle.append(arrow);
  const tagMenu = element('div', 'preview-tag-filter-menu'); tagMenu.setAttribute('data-preview-tag-filter-menu', ''); tagMenu.hidden = true;
  const allTags = element('button', 'preview-tag-filter-all', 'All Labels'); allTags.type = 'button'; allTags.setAttribute('data-preview-tag-filter-all', ''); tagMenu.append(allTags);
  const tags = [...new Set(columns.flatMap(column => {
    const item = metadata[column] || {};
    return [item.kind, item.pinned ? 'PINNED' : 'UN_PINNED'].filter(Boolean);
  }))];
  tags.forEach(tag => { const label = element('label'); const input = element('input'); input.type = 'checkbox'; input.value = tag; label.append(input, element('span', '', tag)); tagMenu.append(label); });
  tagFilter.append(tagToggle, tagMenu); toolbar.append(searchLabel, tagFilter);
  let exportHandler = null;
  if (exportControl instanceof HTMLElement) {
    toolbar.append(exportControl);
    if (typeof exportRequest === 'function') {
      exportHandler = async (event) => {
        event.preventDefault();
        if (exportControl.disabled) return;
        exportControl.disabled = true;
        try {
          await exportRequest({
            column_filters: toolbar.previewColumnFilters?.() || {},
          });
        } catch (error) {
          showInfoDialog(error.message || 'Unable to export the filtered dataset.', {title: 'Export CSV', tone: 'error'});
        } finally {
          exportControl.disabled = false;
        }
      };
      exportControl.addEventListener('click', exportHandler);
    }
  }
  viewer.append(toolbar);

  const tagViewport = element('div', 'preview-column-tag-viewport'); tagViewport.setAttribute('data-preview-column-tag-viewport', '');
  const tagStrip = element('div', 'preview-column-tag-strip'); tagStrip.setAttribute('data-preview-column-tag-strip', '');
  const classForKind = item => item.class_name || '';
  columns.forEach(column => {
    const item = metadata[column] || {};
    const label = item.label || column;
    const holder = element('div', 'preview-column-tag-item'); holder.setAttribute('data-preview-column-tag-item', '');
    holder.dataset.columnName = column; holder.dataset.columnLabel = label; holder.dataset.columnKind = item.kind || 'Source';
    const pin = element('button', `preview-pinned-badge${item.pinned ? '' : ' is-unpinned'}`, item.pinned ? 'PINNED' : 'UN_PINNED');
    const kindClass = item.class_name === 'gcid-column' ? ' is-metadata' : item.kind === 'Auto-calculated' ? ' is-auto' : item.kind === 'Analysis-derived' ? ' is-analysis' : item.kind === 'CDR-Main' ? ' is-main' : String(item.kind || '').startsWith('CDR-') ? ' is-cdr' : '';
    const kind = element('button', `preview-column-kind-badge${kindClass}`, item.kind || 'Source');
    [pin, kind].forEach((badge, index) => {
      badge.type = 'button'; badge.setAttribute('data-preview-rule-badge', ''); badge.dataset.columnName = column;
      badge.dataset.columnLabel = label; badge.dataset.columnKind = index ? (item.kind || 'Source') : (item.pinned ? 'PINNED' : 'UN_PINNED');
      badge.dataset.columnRule = index ? (item.rule || '') : (item.pinned ? 'This field is pinned and remains available in every Dataset Preview.' : 'This source-only field is available when it exists in the selected dataset.');
    });
    holder.append(pin, kind); tagStrip.append(holder);
  });
  tagViewport.append(tagStrip); viewer.append(tagViewport);

  const wrap = element('div', 'table-wrap data-table-wrap dataset-preview-table-wrap'); wrap.setAttribute('data-horizontal-wheel-scroll', ''); wrap.tabIndex = 0;
  const table = element('table', 'dataset-preview-table'); table.setAttribute('data-preview-filter-table', ''); table.setAttribute('data-server-preview-table', '');
  const thead = element('thead'), headerRow = element('tr');
  columns.forEach(column => { const item = metadata[column] || {}; const th = element('th', classForKind(item)); th.dataset.columnName = column; th.dataset.columnLabel = item.label || column; th.dataset.columnKind = item.kind || 'Source'; th.dataset.columnPinned = item.pinned ? 'true' : 'false'; th.dataset.columnRule = item.rule || ''; th.append(element('span', '', item.label || column)); headerRow.append(th); });
  thead.append(headerRow); table.append(thead, element('tbody')); wrap.append(table); viewer.append(wrap);

  const footer = element('div', 'preview-server-footer');
  const svgIcon = pathData => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    pathData.forEach(data => { const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); path.setAttribute('d', data); svg.append(path); });
    return svg;
  };
  const clear = element('button', 'preview-clear-filters'); clear.type = 'button'; clear.disabled = true; clear.setAttribute('data-preview-clear-filters', '');
  const clearLabel = element('span', '', 'Clear 0 Filters'); clearLabel.setAttribute('data-preview-clear-label', ''); clear.append(clearLabel);
  clear.prepend(svgIcon(['M4 5h16', 'M8 5V3h8v2m-9 3 .7 12h8.6L17 8', 'M10 11v6m4-6v6']));
  const pager = element('nav', 'preview-pagination'); pager.setAttribute('aria-label', 'Dataset preview pages');
  const pageButton = (attribute, label, paths) => { const button = element('button'); button.type = 'button'; button.disabled = true; button.setAttribute(attribute, ''); button.setAttribute('aria-label', label); button.title = label; button.append(svgIcon(paths)); return button; };
  const first = pageButton('data-preview-first-page', 'First page', ['M5 5v14', 'M18 6l-6 6 6 6', 'M12 6l-6 6 6 6']); const previous = pageButton('data-preview-previous-page', 'Previous page', ['M15 6l-6 6 6 6']);
  const pageStatus = element('span', '', 'Page 1 of 1'); pageStatus.setAttribute('data-preview-page-status', '');
  const next = pageButton('data-preview-next-page', 'Next page', ['M9 6l6 6-6 6']); const last = pageButton('data-preview-last-page', 'Last page', ['M19 5v14', 'M6 6l6 6-6 6', 'M12 6l6 6-6 6']);
  pager.append(first, previous, pageStatus, next, last);
  const status = element('p', 'preview-table-filter-status'); status.setAttribute('data-preview-filter-status', ''); status.setAttribute('aria-live', 'polite');
  footer.append(clear, pager, status); viewer.append(footer); host.replaceChildren(viewer);
  toolbar.previewRequest = async request => {
    const response = await requestPage(request);
    const responseRows = Array.isArray(response.rows) ? response.rows : [];
    return {
      ...response,
      page: Number(response.page ?? request.page ?? 0),
      total: Number(response.total ?? response.summary?.visible_rows ?? responseRows.length),
      unfiltered_total: Number(response.unfiltered_total ?? response.chart_total ?? response.summary?.matched_rows ?? payload.chart_total ?? payload.total ?? responseRows.length),
      rows: responseRows.map(row => Array.isArray(row) ? Object.fromEntries(columns.map((column, index) => [column, row[index] ?? ''])) : row),
    };
  };
  const initialRows = Array.isArray(payload.rows) ? payload.rows : [];
  table.tBodies[0].replaceChildren(...initialRows.map(row => {
    const record = Array.isArray(row) ? Object.fromEntries(columns.map((column, index) => [column, row[index] ?? ''])) : row;
    const tr = element('tr'); columns.forEach(column => { const td = element('td', classForKind(metadata[column] || {}), record[column] ?? ''); tr.append(td); }); return tr;
  }));
  const destroyPreview = initializeServerDatasetPreview(toolbar);
  host.unifiedDatasetViewerDestroy = () => {
    destroyPreview?.();
    if (exportHandler) exportControl.removeEventListener('click', exportHandler);
  };
  return {viewer, reload: () => toolbar.previewRequest({page: 0, column_filters: {}, filter_column: null})};
};

document.querySelectorAll('[data-preview-dataset-switch]').forEach((input) => {
  const switcher = input.closest('.preview-dataset-switcher');
  const menu = switcher?.querySelector('[data-preview-dataset-switch-menu]');
  const toggle = switcher?.querySelector('[data-preview-dataset-switch-toggle]');
  const options = Array.from(menu?.querySelectorAll('[data-url]') || []);
  const updateOptions = () => {
    const term = input.value.trim().toLocaleLowerCase();
    options.forEach((option) => { option.hidden = Boolean(term) && !option.dataset.datasetLabel.toLocaleLowerCase().includes(term); });
    if (menu) menu.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };
  input.addEventListener('focus', () => {
    input.select();
    options.forEach((option) => { option.hidden = false; });
    if (menu) menu.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  });
  input.addEventListener('input', updateOptions);
  toggle?.addEventListener('click', () => {
    const opening = menu?.hidden ?? true;
    options.forEach((option) => { option.hidden = false; });
    if (menu) menu.hidden = !opening;
    input.setAttribute('aria-expanded', String(opening));
    if (opening) { input.focus(); input.select(); }
  });
  options.forEach((option) => option.addEventListener('mousedown', (event) => {
    event.preventDefault();
    showLoadingOverlay(
      'Loading Workspace Dataset',
      `Please wait while ${option.dataset.datasetLabel || 'the selected dataset'} is loaded.`,
    );
    window.requestAnimationFrame(() => window.location.assign(option.dataset.url));
  }));
  document.addEventListener('click', (event) => {
    if (switcher?.contains(event.target)) return;
    if (menu) menu.hidden = true;
    input.setAttribute('aria-expanded', 'false');
  });
});

const previewRuleOverlay = document.querySelector('[data-preview-rule-overlay]');
const previewBadgeTooltip = document.querySelector('[data-preview-badge-tooltip]');
let previewRuleTrigger = null;
const closePreviewRule = (restoreFocus = false) => {
  if (!previewRuleOverlay || previewRuleOverlay.hidden) return;
  previewRuleOverlay.hidden = true;
  if (restoreFocus) previewRuleTrigger?.focus();
  previewRuleTrigger = null;
};
document.addEventListener('click', (event) => {
  const badge = event.target.closest?.('[data-preview-rule-badge]');
  if (!badge || !previewRuleOverlay) return;
  previewRuleTrigger = badge;
  if (previewBadgeTooltip) previewBadgeTooltip.hidden = true;
  previewRuleOverlay.querySelector('[data-preview-rule-title]').textContent = badge.dataset.columnLabel || 'Field';
  previewRuleOverlay.querySelector('[data-preview-rule-kind]').textContent = badge.dataset.columnKind || 'Field rule';
  previewRuleOverlay.querySelector('[data-preview-rule-text]').textContent = badge.dataset.columnRule || '';
  previewRuleOverlay.hidden = false;
  previewRuleOverlay.querySelector('[data-preview-rule-close]')?.focus();
});
previewRuleOverlay?.querySelector('[data-preview-rule-close]')?.addEventListener('click', () => closePreviewRule(true));
previewRuleOverlay?.addEventListener('click', (event) => { if (event.target === previewRuleOverlay) closePreviewRule(true); });
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !previewRuleOverlay || previewRuleOverlay.hidden) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closePreviewRule(true);
}, true);
const hidePreviewBadgeTooltip = () => { if (previewBadgeTooltip) previewBadgeTooltip.hidden = true; };
const showPreviewBadgeTooltip = (badge) => {
  if (!previewBadgeTooltip) return;
  previewBadgeTooltip.querySelector('[data-preview-badge-tooltip-kind]').textContent = badge.dataset.columnKind || 'Field rule';
  previewBadgeTooltip.querySelector('[data-preview-badge-tooltip-title]').textContent = badge.dataset.columnLabel || 'Field';
  previewBadgeTooltip.querySelector('[data-preview-badge-tooltip-rule]').textContent = badge.dataset.columnRule || '';
  previewBadgeTooltip.hidden = false;
  const bounds = badge.getBoundingClientRect();
  const tooltipBounds = previewBadgeTooltip.getBoundingClientRect();
  const left = Math.max(12, Math.min(bounds.left + bounds.width / 2 - tooltipBounds.width / 2, window.innerWidth - tooltipBounds.width - 12));
  const below = bounds.bottom + 8;
  const top = below + tooltipBounds.height < window.innerHeight - 12 ? below : Math.max(12, bounds.top - tooltipBounds.height - 8);
  previewBadgeTooltip.style.left = `${left}px`;
  previewBadgeTooltip.style.top = `${top}px`;
};
document.addEventListener('pointerover', (event) => { const badge = event.target.closest?.('[data-preview-rule-badge]'); if (badge) showPreviewBadgeTooltip(badge); });
document.addEventListener('pointerout', (event) => { if (event.target.closest?.('[data-preview-rule-badge]')) hidePreviewBadgeTooltip(); });
document.addEventListener('focusin', (event) => { const badge = event.target.closest?.('[data-preview-rule-badge]'); if (badge) showPreviewBadgeTooltip(badge); });
document.addEventListener('focusout', (event) => { if (event.target.closest?.('[data-preview-rule-badge]')) hidePreviewBadgeTooltip(); });

document.querySelectorAll('[data-preview-table-filters]').forEach((filters) => {
  const panel = filters.closest('.dataset-preview-panel');
  const table = panel?.querySelector('[data-preview-filter-table]');
  const columnInput = filters.querySelector('[data-preview-column-filter]');
  const rowInput = filters.querySelector('[data-preview-row-filter]');
  const status = filters.querySelector('[data-preview-filter-status]');
  const tagFilter = filters.querySelector('[data-preview-tag-filter]');
  const tagFilterToggle = tagFilter?.querySelector('[data-preview-tag-filter-toggle]');
  const tagFilterLabel = tagFilterToggle?.querySelector('[data-preview-tag-filter-label]');
  const tagFilterMenu = tagFilter?.querySelector('[data-preview-tag-filter-menu]');
  const tagFilterAll = tagFilterMenu?.querySelector('[data-preview-tag-filter-all]');
  if (!table || !columnInput || !rowInput) return;

  const headers = Array.from(table.querySelectorAll('thead th'));
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const tagItems = Array.from(panel?.querySelectorAll('[data-preview-column-tag-item]') || []);
  const tagStrip = panel?.querySelector('[data-preview-column-tag-strip]');
  const tableWrap = panel?.querySelector('.dataset-preview-table-wrap');
  const valueFilters = new Map();
  const selectedTags = new Set();
  let openColumnMenu = null;
  const termsFor = (input) => String(input.value || '')
    .split(',')
    .map((term) => term.trim().toLocaleLowerCase())
    .filter(Boolean);
  const matchesAny = (value, terms) => !terms.length || terms.some((term) => value.includes(term));

  const applyPreviewFilters = () => {
    const columnTerms = termsFor(columnInput);
    const rowTerms = termsFor(rowInput);
    const visibleColumns = headers.map((header, index) => {
      const visible = matchesAny((header.dataset.columnLabel || header.textContent).toLocaleLowerCase(), columnTerms)
        && (!selectedTags.size || Array.from(selectedTags).some((tag) => (
          tag === (header.dataset.columnKind || '')
          || (tag === 'PINNED' && header.dataset.columnPinned === 'true')
          || (tag === 'UN_PINNED' && header.dataset.columnPinned !== 'true')
        )));
      header.hidden = !visible;
      if (tagItems[index]) tagItems[index].hidden = !visible;
      rows.forEach((row) => {
        const cell = row.cells[index];
        if (cell) cell.hidden = !visible;
      });
      return visible;
    });
    let visibleRowCount = 0;
    rows.forEach((row) => {
      // Row filtering searches every original cell. It remains predictable even
      // when a separate column-name filter temporarily hides matching cells.
      const rowText = Array.from(row.cells).map((cell) => cell.textContent.toLocaleLowerCase()).join(' ');
      const matchesColumnValues = Array.from(valueFilters.entries()).every(([columnIndex, accepted]) => {
        const cellValue = String(row.cells[columnIndex]?.textContent || '').trim();
        return accepted.has(cellValue);
      });
      const visible = matchesAny(rowText, rowTerms) && matchesColumnValues;
      row.hidden = !visible;
      if (visible) visibleRowCount += 1;
    });
    if (status) {
      const visibleColumnCount = visibleColumns.filter(Boolean).length;
      const activeValueFilters = valueFilters.size ? ` · ${valueFilters.size} column filter${valueFilters.size === 1 ? '' : 's'} active` : '';
      status.textContent = `Showing ${visibleRowCount} of ${rows.length} rows · ${visibleColumnCount} of ${headers.length} columns${activeValueFilters}`;
    }
    requestAnimationFrame(() => requestAnimationFrame(syncTagStrip));
  };

  const syncTagStrip = () => {
    if (!tagStrip || !tableWrap) return;
    tagItems.forEach((item) => { item.style.width = ''; });
    tagStrip.style.width = `${table.scrollWidth}px`;
    headers.forEach((header, index) => {
      if (tagItems[index]) tagItems[index].style.width = `${header.getBoundingClientRect().width}px`;
    });
    tagStrip.style.transform = `translateX(${-tableWrap.scrollLeft}px)`;
  };

  const closeColumnMenu = () => {
    if (!openColumnMenu) return;
    openColumnMenu.trigger.setAttribute('aria-expanded', 'false');
    openColumnMenu.menu.remove();
    openColumnMenu = null;
  };

  const openValueMenu = (header, trigger, columnIndex) => {
    if (openColumnMenu?.trigger === trigger) {
      closeColumnMenu();
      return;
    }
    closeColumnMenu();
    const rowTerms = termsFor(rowInput);
    const availableRows = rows.filter((row) => {
      const rowText = Array.from(row.cells).map((cell) => cell.textContent.toLocaleLowerCase()).join(' ');
      const matchesOtherFilters = Array.from(valueFilters.entries()).every(([otherIndex, accepted]) => (
        otherIndex === columnIndex || accepted.has(String(row.cells[otherIndex]?.textContent || '').trim())
      ));
      return matchesAny(rowText, rowTerms) && matchesOtherFilters;
    });
    const values = Array.from(new Set(availableRows.map((row) => String(row.cells[columnIndex]?.textContent || '').trim())))
      .sort((left, right) => left.localeCompare(right, undefined, {numeric: true, sensitivity: 'base'}));
    const activeValues = valueFilters.get(columnIndex);
    const selectedValues = new Set(activeValues ? Array.from(activeValues) : values);
    const menu = document.createElement('section');
    menu.className = 'preview-column-filter-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filter ${trigger.dataset.columnLabel}`);

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'preview-column-filter-search';
    search.placeholder = 'Search values';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', `Search ${trigger.dataset.columnLabel} values`);

    const toolbar = document.createElement('div');
    toolbar.className = 'preview-column-filter-toolbar';
    const selectAllNone = document.createElement('button');
    selectAllNone.type = 'button';
    selectAllNone.textContent = 'Select All/None';
    toolbar.append(selectAllNone);

    const options = document.createElement('div');
    options.className = 'preview-column-filter-options';
    values.forEach((value) => {
      const option = document.createElement('label');
      option.className = 'preview-column-filter-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = value;
      checkbox.checked = selectedValues.has(value);
      checkbox.setAttribute('data-preview-value-option', '');
      const caption = document.createElement('span');
      caption.textContent = value || '(Blank)';
      option.append(checkbox, caption);
      options.append(option);
    });

    const footer = document.createElement('div');
    footer.className = 'preview-column-filter-footer';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'preview-column-filter-cancel';
    cancel.textContent = 'Cancel';
    const apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'preview-column-filter-apply';
    apply.textContent = 'Apply';
    footer.append(cancel, apply);
    menu.append(search, toolbar, options, footer);
    document.body.append(menu);

    const positionMenu = () => {
      const bounds = trigger.getBoundingClientRect();
      const width = Math.min(300, window.innerWidth - 20);
      menu.style.width = `${width}px`;
      menu.style.left = `${Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10))}px`;
      const preferredTop = bounds.bottom + 5;
      const menuHeight = menu.offsetHeight;
      menu.style.top = `${preferredTop + menuHeight <= window.innerHeight - 10 ? preferredTop : Math.max(10, bounds.top - menuHeight - 5)}px`;
    };
    positionMenu();
    trigger.setAttribute('aria-expanded', 'true');
    openColumnMenu = {menu, trigger};

    search.addEventListener('input', () => {
      const term = search.value.trim().toLocaleLowerCase();
      options.querySelectorAll('.preview-column-filter-option').forEach((option) => {
        option.hidden = Boolean(term) && !option.textContent.toLocaleLowerCase().includes(term);
      });
    });
    selectAllNone.addEventListener('click', () => {
      const visible = Array.from(options.querySelectorAll('.preview-column-filter-option:not([hidden]) input'));
      const shouldSelect = visible.some((checkbox) => !checkbox.checked);
      visible.forEach((checkbox) => { checkbox.checked = shouldSelect; });
    });
    cancel.addEventListener('click', closeColumnMenu);
    apply.addEventListener('click', () => {
      const accepted = new Set(Array.from(options.querySelectorAll('[data-preview-value-option]:checked')).map((checkbox) => checkbox.value));
      if (accepted.size === values.length) valueFilters.delete(columnIndex);
      else valueFilters.set(columnIndex, accepted);
      header.classList.toggle('has-value-filter', valueFilters.has(columnIndex));
      applyPreviewFilters();
      closeColumnMenu();
    });
    menu.addEventListener('click', (event) => event.stopPropagation());
    requestAnimationFrame(() => search.focus());
  };

  headers.forEach((header, columnIndex) => {
    const columnLabel = header.textContent.trim();
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'preview-column-filter-trigger';
    trigger.dataset.columnLabel = columnLabel;
    trigger.setAttribute('aria-label', `Filter ${columnLabel}`);
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    const caption = document.createElement('span');
    caption.textContent = columnLabel;
    const icon = document.createElement('span');
    icon.className = 'preview-column-filter-icon';
    icon.textContent = '▾';
    icon.setAttribute('aria-hidden', 'true');
    trigger.append(caption, icon);
    header.replaceChildren(trigger);
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      openValueMenu(header, trigger, columnIndex);
    });
  });

  columnInput.addEventListener('input', applyPreviewFilters);
  rowInput.addEventListener('input', applyPreviewFilters);
  tagFilterToggle?.addEventListener('click', (event) => {
    event.stopPropagation();
    const opening = tagFilterMenu?.hidden ?? true;
    if (tagFilterMenu) tagFilterMenu.hidden = !opening;
    tagFilterToggle.setAttribute('aria-expanded', String(opening));
  });
  tagFilterMenu?.addEventListener('click', (event) => event.stopPropagation());
  tagFilterAll?.addEventListener('click', () => {
    selectedTags.clear();
    tagFilterMenu?.querySelectorAll('input').forEach((checkbox) => { checkbox.checked = false; });
    if (tagFilterLabel) tagFilterLabel.textContent = 'All Labels';
    applyPreviewFilters();
    requestAnimationFrame(() => requestAnimationFrame(syncTagStrip));
    if (tagFilterMenu) tagFilterMenu.hidden = true;
    tagFilterToggle?.setAttribute('aria-expanded', 'false');
  });
  tagFilterMenu?.querySelectorAll('input').forEach((checkbox) => checkbox.addEventListener('change', () => {
    if (checkbox.checked) selectedTags.add(checkbox.value); else selectedTags.delete(checkbox.value);
    if (tagFilterLabel) tagFilterLabel.textContent = selectedTags.size ? `${selectedTags.size} Label${selectedTags.size === 1 ? '' : 's'}` : 'All Labels';
    applyPreviewFilters();
    requestAnimationFrame(() => requestAnimationFrame(syncTagStrip));
  }));
  document.addEventListener('click', () => {
    closeColumnMenu();
    if (tagFilterMenu) tagFilterMenu.hidden = true;
    tagFilterToggle?.setAttribute('aria-expanded', 'false');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeColumnMenu();
  });
  window.addEventListener('resize', closeColumnMenu);
  tableWrap?.addEventListener('scroll', () => { closeColumnMenu(); syncTagStrip(); }, {passive: true});
  window.addEventListener('resize', syncTagStrip);
  applyPreviewFilters();
  requestAnimationFrame(syncTagStrip);
});

document.querySelectorAll('[data-catalogue-editor]').forEach((editor) => {
  const table = editor.querySelector('[data-catalogue-editor-table]');
  const requestedRowValue = new URLSearchParams(window.location.search).get('focus_row');
  const requestedRowIndex = requestedRowValue === null ? Number.NaN : Number(requestedRowValue);
  const saveForm = editor.querySelector('[data-catalogue-editor-save]');
  const reenumerate = editor.querySelector('[data-catalogue-reenumerate]');
  const closeDialog = editor.querySelector('[data-catalogue-editor-close-dialog]');
  const contentField = editor.querySelector('[data-catalogue-editor-content]');
  const heading = editor.querySelector('[data-catalogue-editor-heading]');
  const copy = editor.querySelector('[data-catalogue-editor-copy]');
  const optionsLabel = editor.querySelector('[data-catalogue-editor-options-label]');
  const options = editor.querySelector('[data-catalogue-editor-options]');
  const labelFormatControl = editor.querySelector('[data-catalogue-editor-label-format]');
  const labelFormatColor = editor.querySelector('[data-catalogue-editor-label-format-color]');
  const labelFormatColorValue = editor.querySelector('[data-catalogue-editor-label-format-colour-value]');
  const labelFormatFont = editor.querySelector('[data-catalogue-editor-label-format-font]');
  const labelFormatSize = editor.querySelector('[data-catalogue-editor-label-format-size]');
  const labelFormatBold = editor.querySelector('[data-catalogue-editor-label-format-bold]');
  const labelFormatItalic = editor.querySelector('[data-catalogue-editor-label-format-italic]');
  const labelFormatUnderline = editor.querySelector('[data-catalogue-editor-label-format-underline]');
  const labelFormatAutomatic = editor.querySelector('[data-catalogue-editor-label-format-automatic]');
  const kpiAggregationLabel = editor.querySelector('[data-catalogue-editor-kpi-aggregation-label]');
  const kpiAggregation = editor.querySelector('[data-catalogue-editor-kpi-aggregation]');
  const apply = editor.querySelector('[data-catalogue-editor-apply]');
  const helper = editor.querySelector('.catalogue-editor-helper');
  const helperClose = editor.querySelector('[data-catalogue-editor-helper-close]');
  const filterBuilder = editor.querySelector('[data-catalogue-filter-builder]');
  const filterConditions = editor.querySelector('[data-catalogue-filter-conditions]');
  const addFilter = editor.querySelector('[data-catalogue-filter-add]');
  const chartPreview = editor.querySelector('[data-catalogue-chart-preview]');
  const chartPreviewDialog = chartPreview?.querySelector('.catalogue-chart-preview-dialog');
  const chartPreviewTitle = editor.querySelector('[data-catalogue-chart-preview-title]');
  const chartPreviewSummary = editor.querySelector('[data-catalogue-chart-preview-summary]');
  const chartPreviewTable = editor.querySelector('[data-catalogue-chart-preview-table]');
  const chartPreviewClose = editor.querySelector('[data-catalogue-chart-preview-close]');
  const chartPreviewTableWrap = chartPreviewTable?.closest('.table-wrap');
  const chartPreviewImage = editor.querySelector('[data-catalogue-chart-preview-image]');
  const chartPreviewImageContent = editor.querySelector('[data-catalogue-chart-preview-image-content]');
  const chartPreviewSandbox = editor.querySelector('[data-catalogue-chart-preview-sandbox]');
  const chartPreviewFields = editor.querySelector('[data-catalogue-chart-preview-fields]');
  const chartPreviewData = editor.querySelector('[data-catalogue-chart-preview-data]');
  const chartPreviewDataOverlay = editor.querySelector('[data-catalogue-chart-preview-data-overlay]');
  const chartPreviewDataPanel = editor.querySelector('[data-catalogue-chart-preview-data-panel]');
  const chartPreviewDataExport = editor.querySelector('[data-catalogue-chart-preview-data-export]');
  const chartPreviewUpdate = editor.querySelector('[data-catalogue-chart-preview-update]');
  const chartPreviewActionClose = editor.querySelector('[data-catalogue-chart-preview-action-close]');
  let chartPreviewImageUrl = '';
  let chartPreviewRow = null;
  let chartPreviewTimer = null;
  let chartPreviewController = null;
  let chartPreviewRequest = 0;
  const chartPreviewDatasetPageSize = 100;
  if (!table || !saveForm || !contentField || !heading || !copy || !optionsLabel || !options || !apply || !helper) return;

  // The editor panel uses backdrop effects, which establish a containing block
  // for fixed descendants. Move the floating helper to the document root so
  // its viewport coordinates line up exactly with the active table cell.
  document.body.append(helper);

  let suggestions = {};
  try { suggestions = JSON.parse(editor.dataset.editorSuggestions || '{}'); } catch (_error) { suggestions = {}; }
  let calculatedDimensions = [];
  let availableDimensionColumns = suggestions.columns || {};
  try { calculatedDimensions = JSON.parse(editor.dataset.calculatedDimensions || '[]'); } catch (_error) { calculatedDimensions = []; }
  const initialCalculatedDimensionNames = new Set(calculatedDimensions.map((item) => String(item.name || '').toLocaleLowerCase()));
  const baseSuggestionColumns = Object.fromEntries(Object.entries(suggestions.columns || {}).map(([source, values]) => [
    source, values.filter((value) => !initialCalculatedDimensionNames.has(String(value).toLocaleLowerCase())),
  ]));
  const refreshCalculatedDimensionSuggestions = () => {
    suggestions.columns = Object.fromEntries(Object.entries(baseSuggestionColumns).map(([source, values]) => [
      source,
      [...new Set([
        ...values,
        ...calculatedDimensions.filter((item) => (item.sources || []).includes(source)).map((item) => item.name),
      ])].sort((left, right) => left.localeCompare(right)),
    ]));
    editor.dataset.editorSuggestions = JSON.stringify(suggestions);
    editor.dataset.calculatedDimensions = JSON.stringify(calculatedDimensions);
  };
  refreshCalculatedDimensionSuggestions();

  const saveCalculatedDimensions = async (renames = [], materialize = true, showNotice = true) => {
    const response = await fetch(editor.dataset.calculatedDimensionsUrl, {
      method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dimensions: calculatedDimensions, renames, materialize}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Unable to save auto-calculated fields.');
    calculatedDimensions = Array.isArray(payload.dimensions) ? payload.dimensions : calculatedDimensions;
    refreshCalculatedDimensionSuggestions();
    if (payload.materialization_status_url) {
      monitorAutoCalculatedFieldJob(payload.materialization_status_url, showNotice ? payload.notice : '');
    } else if (showNotice && payload.notice) {
      showInfoDialog(payload.notice, {title: 'Auto-calculated Fields'});
    }
    return payload;
  };

  const openCalculatedDimensionsManager = async () => {
    try {
      const response = await fetch(editor.dataset.calculatedDimensionsUrl, {credentials: 'same-origin', cache: 'no-store'});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to load auto-calculated fields.');
      calculatedDimensions = Array.isArray(payload.dimensions) ? payload.dimensions : [];
      availableDimensionColumns = payload.columns && typeof payload.columns === 'object' ? payload.columns : suggestions.columns || {};
      refreshCalculatedDimensionSuggestions();
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to load auto-calculated fields.', {
        title: 'Auto-calculated Fields', tone: 'error',
      });
      return;
    }
    let managerWindow = window;
    try {
      if (window.top !== window && window.top.location.origin === window.location.origin) managerWindow = window.top;
    } catch (_error) { managerWindow = window; }
    const managerDocument = managerWindow.document;
    const managerConfirm = (...args) => (
      typeof managerWindow.showConfirmDialog === 'function'
        ? managerWindow.showConfirmDialog(...args)
        : showConfirmDialog(...args)
    );
    const managerInfo = (...args) => (
      typeof managerWindow.showInfoDialog === 'function'
        ? managerWindow.showInfoDialog(...args)
        : showInfoDialog(...args)
    );
    const managerShowLoading = (...args) => (
      typeof managerWindow.showLoadingOverlay === 'function'
        ? managerWindow.showLoadingOverlay(...args)
        : showLoadingOverlay(...args)
    );
    const managerHideLoading = () => (
      typeof managerWindow.hideLoadingOverlay === 'function'
        ? managerWindow.hideLoadingOverlay()
        : hideLoadingOverlay()
    );
    const overlay = document.createElement('div'); overlay.className = 'confirm-overlay calculated-dimensions-overlay';
    const panel = document.createElement('section'); panel.className = 'confirm-panel calculated-dimensions-dialog';
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    const header = document.createElement('div'); header.className = 'catalogue-chart-preview-header';
    const headingWrap = document.createElement('div');
    const eyebrow = document.createElement('p'); eyebrow.className = 'eyebrow'; eyebrow.textContent = 'Active Workspace';
    const title = document.createElement('h3'); title.textContent = 'Auto-calculated Fields';
    const close = document.createElement('button'); close.type = 'button'; close.className = 'calculated-dimensions-close calculated-dimensions-icon-close report-chart-viewer-close'; close.textContent = '×'; close.title = 'Close'; close.setAttribute('aria-label', 'Close auto-calculated fields');
    headingWrap.append(eyebrow, title); header.append(headingWrap, close);
    const note = document.createElement('p'); note.className = 'form-note';
    note.textContent = 'Use ordered condition => result rules or one Tableau-style IF / THEN / ELSEIF / ELSE / END expression. Type [ to select a source field from the chosen CDR types. Expressions may be nested and comparisons ignore case.';
    const list = document.createElement('div'); list.className = 'calculated-dimensions-list';
    const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Add Auto-calculated Field';
    const managerActions = document.createElement('div'); managerActions.className = 'calculated-dimensions-manager-actions';
    const panelClose = document.createElement('button'); panelClose.type = 'button'; panelClose.className = 'calculated-dimensions-close'; panelClose.textContent = 'Close';
    const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save'; save.disabled = true;
    const saveAndMaterialize = document.createElement('button'); saveAndMaterialize.type = 'button'; saveAndMaterialize.textContent = 'Save & Materialize'; saveAndMaterialize.disabled = true;
    managerActions.append(add, save, saveAndMaterialize, panelClose);
    const form = document.createElement('div'); form.className = 'calculated-dimension-editor'; form.hidden = true;
    panel.append(header, note, list, managerActions, form); overlay.append(panel); managerDocument.body.append(overlay);
    let editingIndex = null, savedEditorState = '';
    let fieldAutocompleteControllers = [];
    let persistedDimensions = JSON.parse(JSON.stringify(calculatedDimensions));
    const pendingRenames = new Map();
    const recordPendingRename = (from, to) => {
      let original = from;
      for (const [candidate, current] of pendingRenames) {
        if (current === from) {
          original = candidate;
          pendingRenames.delete(candidate);
          break;
        }
      }
      if (original !== to) pendingRenames.set(original, to);
    };
    const hasPendingChanges = () => JSON.stringify(calculatedDimensions) !== JSON.stringify(persistedDimensions);
    const updateSaveActions = () => {
      const disabled = !hasPendingChanges();
      save.disabled = disabled;
      saveAndMaterialize.disabled = disabled;
    };
    const editorState = () => JSON.stringify(Array.from(form.querySelectorAll('input, textarea')).map((input) => ({
      type: input.type, value: input.value, checked: input.checked,
    })));
    const hasUnsavedEditorChanges = () => !form.hidden && editorState() !== savedEditorState;
    const clearFieldAutocompletes = () => {
      fieldAutocompleteControllers.forEach((controller) => controller.destroy());
      fieldAutocompleteControllers = [];
    };
    const finish = () => {
      clearFieldAutocompletes();
      managerWindow.removeEventListener('keydown', handleEscape, true);
      overlay.remove();
    };
    const requestFinish = async () => {
      if (hasUnsavedEditorChanges() && !await managerConfirm(
        'This Auto-calculated Field has unsaved changes. Close without applying them?',
        {title: 'Unapplied Auto-calculated Field', confirmLabel: 'Discard and Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return;
      if (hasPendingChanges() && !await managerConfirm(
        'There are applied Auto-calculated Field changes that have not been saved. Close and discard them?',
        {title: 'Unsaved Auto-calculated Fields', confirmLabel: 'Discard and Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return;
      finish();
    };
    const handleEscape = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (fieldAutocompleteControllers.some((controller) => controller.isOpen())) {
        fieldAutocompleteControllers.forEach((controller) => controller.close());
        return;
      }
      if (form.hidden) void requestFinish(); else void returnToList();
    };
    close.addEventListener('click', () => { void requestFinish(); });
    panelClose.addEventListener('click', () => {
      if (form.hidden) void requestFinish(); else void returnToList();
    });
    overlay.addEventListener('click', (event) => { if (event.target === overlay) void requestFinish(); });
    managerWindow.addEventListener('keydown', handleEscape, true);
    const restoreManagerActions = () => { managerActions.hidden = false; managerActions.append(add, save, saveAndMaterialize, panelClose); };
    const returnToList = async (confirmDiscard = true) => {
      if (form.hidden) return false;
      if (confirmDiscard && hasUnsavedEditorChanges() && !await managerConfirm(
        'This Auto-calculated Field has unsaved changes. Close without saving them?',
        {title: 'Unsaved Auto-calculated Field', confirmLabel: 'Close', cancelLabel: 'Keep editing', tone: 'warning'},
      )) return false;
      clearFieldAutocompletes();
      form.hidden = true;
      list.hidden = false;
      restoreManagerActions();
      renderList();
      updateSaveActions();
      add.focus();
      return true;
    };

    const editDimension = (index = null) => {
      editingIndex = index;
      const current = index === null ? {name: '', sources: ['cdr-data'], default: '', default_from: '', rules: []} : calculatedDimensions[index];
      clearFieldAutocompletes();
      form.replaceChildren(); form.hidden = false; list.hidden = true; managerActions.hidden = true;
      const field = (labelText, value = '') => {
        const label = document.createElement('label'); label.textContent = labelText;
        const input = document.createElement('input'); input.type = 'text'; input.value = value; label.append(input); form.append(label); return input;
      };
      const name = field('Name', current.name || '');
      const defaultValue = field('Default value (optional)', current.default || '');
      const defaultFrom = field('Default source fields (optional, use [Field A] OR [Field B])', current.default_from || '');
      const sources = document.createElement('div'); sources.className = 'calculated-dimension-sources';
      const sourcesLabel = document.createElement('span'); sourcesLabel.textContent = 'Available for';
      const sourceMenu = document.createElement('details'); sourceMenu.className = 'calculated-dimension-source-menu';
      const sourceSummary = document.createElement('summary');
      const sourceChoices = document.createElement('div'); sourceChoices.className = 'calculated-dimension-source-choices';
      const updateSourceSummary = () => {
        const selected = Array.from(sourceChoices.querySelectorAll('input:checked')).map((input) => input.value.toUpperCase());
        sourceSummary.textContent = selected.length ? selected.join(', ') : 'Select CDR types';
      };
      ['cdr-data', 'cdr-voice', 'cdr-speech'].forEach((value) => {
        const label = document.createElement('label'); const input = document.createElement('input'); input.type = 'checkbox'; input.value = value;
        input.checked = (current.sources || []).includes(value); label.append(input, document.createTextNode(value.toUpperCase())); sourceChoices.append(label);
      });
      sourceMenu.append(sourceSummary, sourceChoices); sourceMenu.addEventListener('change', () => {
        updateSourceSummary();
        fieldAutocompleteControllers.forEach((controller) => controller.refresh());
      }); configureCalculatedDimensionSourceMenu(sourceMenu, overlay); updateSourceSummary(); sources.append(sourcesLabel, sourceMenu); form.append(sources);
      const rulesLabel = document.createElement('label'); rulesLabel.className = 'calculated-dimension-rules'; rulesLabel.textContent = 'Rules';
      const rules = document.createElement('textarea'); rules.placeholder = "[Test_Result] IN (Completed, Visible Completed) => Success\n\nor\n\nIF ([Mean Data Rate] < 1) THEN 'below1'\nELSE 'Above'\nEND";
      rules.value = current.expression || (current.rules || []).map((rule) => `${rule.when} => ${rule.value}`).join('\n'); rulesLabel.append(rules); form.append(rulesLabel);
      const selectedColumns = () => Array.from(sourceChoices.querySelectorAll('input:checked'))
        .flatMap((checkbox) => [
          ...(availableDimensionColumns[checkbox.value] || []),
          ...calculatedDimensions.filter((dimension) => (dimension.sources || []).includes(checkbox.value)).map((dimension) => dimension.name),
        ]);
      fieldAutocompleteControllers = [defaultFrom, rules]
        .map((field) => configureCalculatedDimensionFieldAutocomplete(field, selectedColumns));
      const actions = document.createElement('div'); actions.className = 'confirm-actions calculated-dimension-rules';
      const discard = document.createElement('button'); discard.type = 'button'; discard.className = 'calculated-dimensions-close'; discard.textContent = 'Discard';
      const apply = document.createElement('button'); apply.type = 'button'; apply.textContent = 'Apply'; actions.append(discard, apply); form.append(actions);
      discard.addEventListener('click', () => { void returnToList(false); });
      apply.addEventListener('click', async () => {
        try {
          const ruleText = rules.value.trim();
          const isExpression = /^IF\b/i.test(ruleText);
          const parsedRules = isExpression ? [] : ruleText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
            const separator = line.lastIndexOf('=>');
            if (separator < 1) throw new Error(`Invalid rule '${line}'. Use condition => result or a complete IF / THEN / END expression.`);
            return {when: formatCalculatedDimensionRuleAliases(line.slice(0, separator)), value: line.slice(separator + 2).trim()};
          });
          const dimension = {
            name: name.value.trim(),
            sources: Array.from(sources.querySelectorAll('input:checked')).map((input) => input.value),
            default: defaultValue.value,
            default_from: formatCalculatedDimensionAliases(defaultFrom.value),
            rules: parsedRules,
            expression: isExpression ? ruleText : '',
          };
          const next = [...calculatedDimensions];
          if (editingIndex === null) next.push(dimension); else next[editingIndex] = dimension;
          const rename = editingIndex === null || current.name === dimension.name ? null : {from: current.name, to: dimension.name};
          calculatedDimensions = next;
          if (rename) recordPendingRename(rename.from, rename.to);
          await returnToList(false);
        } catch (error) {
          managerInfo(error.message || 'Unable to save auto-calculated field.', {title: 'Auto-calculated Fields', tone: 'error'});
        }
      });
      savedEditorState = editorState();
      name.focus();
    };

    const exportDimension = (index) => {
      const query = new URLSearchParams({name: calculatedDimensions[index].name});
      window.location.assign(`${editor.dataset.calculatedDimensionExportUrl}?${query.toString()}`);
    };

    const renderList = () => {
      list.replaceChildren();
      if (!calculatedDimensions.length) { const empty = document.createElement('p'); empty.className = 'form-note'; empty.textContent = 'This workspace has no auto-calculated fields.'; list.append(empty); }
      calculatedDimensions.forEach((dimension, index) => {
        const item = document.createElement('div'); item.className = 'calculated-dimension-item';
        const orderActions = document.createElement('div'); orderActions.className = 'calculated-dimension-order-actions';
        const moveUp = createActionButton('↑', 'move-up', `Move ${dimension.name} up`, 'chart'); delete moveUp.dataset.catalogueChartAction; moveUp.disabled = index === 0;
        const moveDown = createActionButton('↓', 'move-down', `Move ${dimension.name} down`, 'chart'); delete moveDown.dataset.catalogueChartAction; moveDown.disabled = index === calculatedDimensions.length - 1;
        moveUp.addEventListener('click', () => {
          [calculatedDimensions[index - 1], calculatedDimensions[index]] = [calculatedDimensions[index], calculatedDimensions[index - 1]];
          renderList(); updateSaveActions();
        });
        moveDown.addEventListener('click', () => {
          [calculatedDimensions[index], calculatedDimensions[index + 1]] = [calculatedDimensions[index + 1], calculatedDimensions[index]];
          renderList(); updateSaveActions();
        });
        orderActions.append(moveUp, moveDown);
        const identity = document.createElement('div'); const strong = document.createElement('strong'); strong.textContent = dimension.name;
        const sourceText = document.createElement('p'); sourceText.textContent = (dimension.sources || []).map((source) => source.toUpperCase()).join(' · '); identity.append(strong, sourceText);
        const summary = document.createElement('div'); summary.className = 'calculated-dimension-rule-summary';
        (dimension.rules || []).forEach((rule, ruleIndex) => {
          const line = document.createElement('div');
          const number = document.createElement('strong'); number.textContent = `${ruleIndex + 1}.`;
          const condition = document.createElement('code'); condition.textContent = rule.when || 'ELSE';
          const arrow = document.createElement('span'); arrow.textContent = '→';
          const result = document.createElement('b'); result.textContent = rule.value;
          line.append(number, condition, arrow, result); summary.append(line);
        });
        if (dimension.expression) {
          const expression = document.createElement('div'); expression.className = 'calculated-dimension-expression';
          const expressionLabel = document.createElement('strong'); expressionLabel.textContent = 'IF expression';
          const expressionText = document.createElement('pre'); expressionText.textContent = dimension.expression;
          expression.append(expressionLabel, expressionText); summary.append(expression);
        }
        if (dimension.default_from || dimension.default) {
          const fallbackLine = document.createElement('div'); fallbackLine.className = 'calculated-dimension-fallback';
          fallbackLine.textContent = `Fallback: ${dimension.default_from || dimension.default}`; summary.append(fallbackLine);
        }
        const actions = document.createElement('div'); actions.className = 'calculated-dimension-actions';
        const edit = createActionButton('✎', 'edit', `Edit ${dimension.name}`, 'chart'); delete edit.dataset.catalogueChartAction;
        const duplicate = createActionButton('⧉', 'duplicate', `Duplicate ${dimension.name}`, 'chart', 'auto-calculated-field-duplicate'); delete duplicate.dataset.catalogueChartAction;
        const exportButton = createActionButton('↓', 'export', `Export ${dimension.name}`, 'chart', 'auto-calculated-field-export'); delete exportButton.dataset.catalogueChartAction;
        const remove = createActionButton('−', 'delete', `Delete ${dimension.name}`, 'chart', 'catalogue-row-delete auto-calculated-field-remove'); delete remove.dataset.catalogueChartAction;
        edit.addEventListener('click', () => editDimension(index));
        duplicate.addEventListener('click', async () => {
          const names = new Set(calculatedDimensions.map((item) => String(item.name || '').toLocaleLowerCase()));
          let copyName = `${dimension.name} Copy`; let suffix = 2;
          while (names.has(copyName.toLocaleLowerCase())) copyName = `${dimension.name} Copy ${suffix++}`;
          const copy = JSON.parse(JSON.stringify({...dimension, name: copyName}));
          calculatedDimensions = [...calculatedDimensions.slice(0, index + 1), copy, ...calculatedDimensions.slice(index + 1)];
          renderList();
          updateSaveActions();
        });
        exportButton.addEventListener('click', () => exportDimension(index));
        remove.addEventListener('click', async () => {
          if (!await managerConfirm(`Delete auto-calculated field '${dimension.name}'? The deletion will remain in memory until you save.`, {title: 'Delete Auto-calculated Field', confirmLabel: 'Delete', tone: 'danger'})) return;
          const deletedName = String(dimension.name || '').toLocaleLowerCase();
          calculatedDimensions = calculatedDimensions.filter((_item, itemIndex) => itemIndex !== index);
          for (const [from, to] of pendingRenames) {
            if (String(to).toLocaleLowerCase() === deletedName) pendingRenames.delete(from);
          }
          renderList();
          updateSaveActions();
        });
        actions.append(edit, duplicate, exportButton, remove); item.append(orderActions, identity, summary, actions); list.append(item);
      });
    };
    const persistChanges = async (materialize) => {
      if (!hasPendingChanges()) return;
      const action = materialize ? saveAndMaterialize : save;
      const originalLabel = action.textContent;
      try {
        save.disabled = true; saveAndMaterialize.disabled = true;
        action.setAttribute('aria-busy', 'true'); action.textContent = 'Saving…';
        managerShowLoading(
          materialize ? 'Saving and Materializing Auto-calculated Fields' : 'Saving Auto-calculated Fields',
          materialize ? 'Saving the applied changes. Materialization will continue in the background.' : 'Saving the applied changes without starting materialization.',
        );
        await saveCalculatedDimensions(Array.from(pendingRenames, ([from, to]) => ({from, to})), materialize, false);
        persistedDimensions = JSON.parse(JSON.stringify(calculatedDimensions));
        pendingRenames.clear();
        managerHideLoading();
        updateSaveActions();
        finish();
      } catch (error) {
        managerHideLoading();
        updateSaveActions();
        managerInfo(error.message || 'Unable to save auto-calculated fields.', {title: 'Auto-calculated Fields', tone: 'error'});
      } finally {
        action.removeAttribute('aria-busy'); action.textContent = originalLabel;
      }
    };
    save.addEventListener('click', () => { void persistChanges(false); });
    saveAndMaterialize.addEventListener('click', () => { void persistChanges(true); });
    add.addEventListener('click', () => editDimension());
    renderList(); updateSaveActions(); close.focus();
  };
  editor.querySelector('[data-manage-calculated-dimensions]')?.addEventListener('click', () => { void openCalculatedDimensionsManager(); });
  editor.querySelector('[data-catalogue-chart-preview-manage-dimensions]')?.addEventListener('click', () => { void openCalculatedDimensionsManager(); });
  let activeCell = null;
  const catalogueHeaders = Array.from(table.querySelectorAll('thead th[data-catalogue-field]'))
    .map((cell) => cell.dataset.catalogueField);
  const fieldColumns = new Set(['Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend']);
  const assistedFields = new Set(['Layout', 'CDR source', 'KPI', 'Chart type', 'Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend', 'Legend Position', 'Label Position', 'Label Format', 'Axis X Range', 'Axis Y Range', 'Exclude Null/Empty', 'Exclude Zero']);
  const groupingColumns = new Set(['Rows Aggregation', 'Column Aggregation']);
  const validationAlert = document.querySelector('[data-catalogue-validation-alert]');
  const validationMessage = validationAlert?.querySelector('[data-catalogue-validation-message]');
  const canonicalFilterValue = (value) => String(value || '')
    .replace(/\u00a0/g, ' ')
    .split(/\s*;\s*|\s*[\r\n]+\s*/)
    .map((clause) => clause.trim())
    .filter(Boolean)
    .join('; ');
  const displayedFilterValue = (value) => canonicalFilterValue(value).replace(/; /g, ';\n');
  const renderAddedText = (container, value, original = null) => {
    const current = String(value || '');
    if (original === null || current === String(original || '') || current.length <= String(original || '').length) {
      container.append(document.createTextNode(current));
      return;
    }
    const baseline = String(original || '');
    let prefix = 0;
    while (prefix < baseline.length && prefix < current.length && baseline[prefix] === current[prefix]) prefix += 1;
    let suffix = 0;
    while (suffix < baseline.length - prefix && baseline[baseline.length - 1 - suffix] === current[current.length - 1 - suffix]) suffix += 1;
    const addedEnd = current.length - suffix;
    container.append(document.createTextNode(current.slice(0, prefix)));
    const added = document.createElement('mark');
    added.className = 'catalogue-cell-added-text';
    added.textContent = current.slice(prefix, addedEnd);
    container.append(added, document.createTextNode(current.slice(addedEnd)));
  };
  const refreshCellEditedState = (cell) => {
    if (!cell) return;
    const current = cell.dataset.catalogueField === 'Filters' ? canonicalFilterValue(cell.textContent) : cell.textContent.trim();
    cell.classList.toggle('is-edited', current !== (cell.dataset.originalValue || ''));
  };
  const renderFilterCell = (cell, value, original = null) => {
    const clauses = canonicalFilterValue(value).split('; ').filter(Boolean);
    const originalClauses = original === null ? [] : canonicalFilterValue(original).split('; ').filter(Boolean);
    cell.replaceChildren(...clauses.map((clause, index) => {
      const line = document.createElement('div');
      line.className = 'catalogue-filter-cell-line';
      // Inserting a condition shifts every following line. Match an unchanged
      // clause by content before falling back to its former position so moved
      // conditions are not incorrectly painted as newly added text.
      const originalClause = originalClauses.includes(clause) ? clause : (originalClauses[index] || '');
      renderAddedText(line, clause, original === null ? null : originalClause);
      if (index < clauses.length - 1) line.append(document.createTextNode(';'));
      return line;
    }));
  };
  const filterValidationError = (value) => {
    const clauses = canonicalFilterValue(value).split('; ').filter(Boolean);
    for (const clause of clauses) {
    const match = clause.match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i);
      if (!match) return `Invalid filter '${clause}': expected 'Column OP value' and a semicolon between conditions.`;
    const operator = match[2].replace(/\s+/g, ' ').toUpperCase();
      if (['IN', 'NOT IN'].includes(operator) && !/^\([^()]+\)$/.test(match[3].trim())) {
        const detail = /\)\s*\S/.test(match[3])
          ? 'a semicolon is required after the closing parenthesis'
          : 'IN values must use parentheses';
        return `Invalid filter '${clause}': ${detail}.`;
      }
    }
    return '';
  };
  const refreshFilterValidationAlert = () => {
    if (!validationAlert) return;
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    let invalid = null;
    for (const row of rows) {
      const value = rowValue(row, 'Filters');
      const error = value ? filterValidationError(value) : '';
      if (!error) continue;
      const slide = rowValue(row, 'Slide') || '?';
      const chart = rows.filter((candidate) => (
        rowValue(candidate, 'Slide') === slide
        && rowValue(candidate, 'CDR source')
        && rows.indexOf(candidate) <= rows.indexOf(row)
      )).length || 1;
      invalid = `Slide: ${slide} - Chart: ${chart} -> ${error}`;
      break;
    }
    if (validationMessage) validationMessage.textContent = invalid || '';
    validationAlert.hidden = !invalid;
  };
  const optionList = (field, cell) => {
    if (field === 'Layout') return suggestions.layouts || [];
    if (field === 'Chart type') return suggestions.chart_types || [];
    if (field === 'Legend Position') return suggestions.legend_positions || [];
    if (field === 'Label Position') return suggestions.label_positions || [];
    if (field === 'Exclude Null/Empty' || field === 'Exclude Zero') return suggestions.boolean_values || ['', 'Yes'];
    if (field === 'CDR source') return Object.keys(suggestions.columns || {}).map((source) => source.replace(/^cdr-/, 'CDR-').replace(/(^|-)\w/g, (letter) => letter.toUpperCase()));
    if (fieldColumns.has(field) || field === 'KPI') {
      const row = cell.closest('tr');
      const source = row?.querySelector('[data-catalogue-field="CDR source"]')?.textContent.trim().toLocaleLowerCase();
      return suggestions.columns?.[source] || [];
    }
    return [];
  };
  const helperCopy = (field) => {
    if (field === 'Layout') return 'Choose one of the layouts defined by the selected PowerPoint template. It replaces the current value.';
    if (field === 'Chart type') return 'Choose one supported chart type. It replaces the current value.';
    if (field === 'CDR source') return 'Choose the CDR source used to create this chart. It replaces the current value.';
    if (field === 'KPI') return 'Choose a processed field and, optionally, an explicit aggregation. COUNT counts non-empty rows; COUNTD counts distinct values.';
    if (field === 'Legend') return 'Select one or more CDR fields to use as the displayed legend labels. Values are stored as a comma-separated list.';
    if (field === 'Legend Position') return 'Leave this empty when the chart has no legend, or choose where the legend is drawn.';
    if (field === 'Label Position') return 'Override value-label placement for any chart: None hides labels; Top, Up, Middle and Down select their chart-aware position. Leave empty to retain automatic placement.';
    if (field === 'Label Format') return 'Choose a color, font and styles. They are stored as a JSON list; leave the cell empty to retain automatic formatting. Tiny labels beside stacked segments retain their segment colour.';
    if (field === 'Axis X Range') return 'Optional horizontal-axis range in chart units: [min,max], [min,] or [,max]. Leave empty to keep automatic limits.';
    if (field === 'Axis Y Range') return 'Optional vertical-axis range in chart units: [min,max], [min,] or [,max]. Percentage charts use values from 0 to 100.';
    if (field === 'Exclude Null/Empty') return 'Choose Yes to exclude rows whose plotted value is null or empty. Leave empty to keep them.';
    if (field === 'Exclude Zero') return 'Choose Yes to exclude rows whose plotted numeric value is exactly zero. Leave empty to keep them.';
    if (field === 'Filters') return 'Build complete conditions from a processed CDR field, operator and real observed value. Conditions are joined with semicolons (AND), and the cell remains manually editable.';
    if (field === 'Rows Aggregation') return 'Select one or more dimensions for the chart category axis or table rows. They are appended with ×.';
    if (field === 'Column Aggregation') return 'Select one or more dimensions for comparison series or table columns. They are appended with ×.';
    return 'This value can be edited directly. Select Layout, Chart type, Filters or Grouping for contextual suggestions.';
  };
  const selectedSource = (cell) => cell?.closest('tr')?.querySelector('[data-catalogue-field="CDR source"]')?.textContent.trim().toLocaleLowerCase() || '';
  const filterOperators = [
    ['=', 'Equals (=)'], ['!=', 'Not equal (!=)'], ['CONTAINS', 'Contains'], ['NOT CONTAINS', 'Not contains'],
    ['IN', 'In list (IN)'], ['NOT IN', 'Not in list (NOT IN)'], ['<', 'Less than (<)'], ['<=', 'Less than or equal (≤)'],
    ['>', 'Greater than (>)'], ['>=', 'Greater than or equal (≥)'],
  ];
  const parseFilterConditions = (raw) => String(raw || '').replace(/\u00a0/g, ' ').split(';').map((clause) => {
    const match = clause.trim().match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i);
    if (!match) return null;
    const [, field, operator, value] = match;
    return { field: field.trim(), operator: operator.replace(/\s+/g, ' ').toUpperCase(), value: value.trim().replace(/^\((.*)\)$/, '$1') };
  }).filter(Boolean);
  const syncFilterCell = () => {
    if (!activeCell || activeCell.dataset.catalogueField !== 'Filters' || !filterConditions) return;
    const clauses = Array.from(filterConditions.querySelectorAll('[data-filter-condition]')).map((row) => {
      const field = row.querySelector('[data-filter-field]')?.value.trim();
      const operator = row.querySelector('[data-filter-operator]')?.value.trim();
      const rawValue = row.querySelector('[data-filter-value]')?.value.trim();
      if (!field || !operator || !rawValue) return '';
      const listOperator = ['IN', 'NOT IN', 'CONTAINS', 'NOT CONTAINS'].includes(operator);
      const value = listOperator && rawValue.includes(',') && !/^\(.+\)$/.test(rawValue) ? `(${rawValue})` : rawValue;
      return `${field} ${operator} ${value}`;
    }).filter(Boolean);
    renderFilterCell(activeCell, clauses.join('; '));
    refreshCellEditedState(activeCell);
    if (activeCell.classList.contains('is-edited')) {
      renderFilterCell(activeCell, clauses.join('; '), activeCell.dataset.originalValue || '');
    }
    refreshFilterValidationAlert();
  };
  const addFilterCondition = (condition = {}) => {
    if (!filterConditions || !activeCell) return;
    const source = selectedSource(activeCell);
    const fields = suggestions.columns?.[source] || [];
    const row = document.createElement('div');
    row.className = 'catalogue-filter-condition';
    row.dataset.filterCondition = '';
    const field = document.createElement('select');
    field.dataset.filterField = '';
    field.dataset.searchableSelect = '';
    field.setAttribute('aria-label', 'Filter field');
    field.append(new Option('Choose field', ''));
    fields.forEach((value) => field.add(new Option(value, value)));
    const normalizedOption = (select, requested) => {
      const normalize = (value) => String(value || '').toLocaleLowerCase().replace(/[^a-z0-9]+/g, '');
      return Array.from(select.options).find((option) => normalize(option.value) === normalize(requested))?.value || requested || '';
    };
    field.value = normalizedOption(field, condition.field);
    const operator = document.createElement('select');
    operator.dataset.filterOperator = '';
    operator.dataset.searchableSelect = '';
    operator.setAttribute('aria-label', 'Filter operator');
    filterOperators.forEach(([value, label]) => operator.add(new Option(label, value)));
    operator.value = normalizedOption(operator, condition.operator || '=');
    const value = document.createElement('input');
    const list = document.createElement('datalist');
    const listId = `catalogue-filter-values-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    value.type = 'text'; value.dataset.filterValue = ''; value.placeholder = 'Choose or type a value'; value.setAttribute('list', listId);
    list.id = listId;
    let valueRequest = 0;
    const updateValues = async () => {
      const request = ++valueRequest;
      const selectedField = field.value;
      list.replaceChildren();
      if (!source || !selectedField) return;
      try {
        const query = new URLSearchParams({
          source, column: selectedField,
          technology: editor.dataset.templateTechnology,
          catalogue_id: editor.dataset.templateIdentifier,
        });
        const response = await fetch(`/admin/catalogue-filter-values?${query.toString()}`, { credentials: 'same-origin' });
        const payload = response.ok ? await response.json() : { values: [] };
        if (request !== valueRequest) return;
        const available = Array.isArray(payload.values) ? payload.values : [];
        list.replaceChildren(...available.map((item) => new Option(item, item)));
      } catch (_error) {
        // A value may always be entered manually if contextual values are unavailable.
      }
    };
    value.value = condition.value || '';
    updateValues();
    const remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'catalogue-filter-remove'; remove.textContent = '−'; remove.title = 'Remove condition'; remove.setAttribute('aria-label', 'Remove filter condition');
    field.addEventListener('change', () => { updateValues(); syncFilterCell(); });
    operator.addEventListener('change', syncFilterCell);
    value.addEventListener('input', syncFilterCell);
    remove.addEventListener('click', () => { row.remove(); syncFilterCell(); });
    row.append(field, operator, value, remove, list);
    filterConditions.append(row);
    setupSearchableSingleSelects();
    // The visual searchable controls are sibling shells. Hydrate them from
    // the native select after they have been mounted, so existing clauses are
    // visible immediately rather than showing their search placeholder.
    window.requestAnimationFrame(() => {
      [field, operator].forEach((select) => {
        const input = select.nextElementSibling?.querySelector('.searchable-select-input');
        if (input) input.value = select.selectedOptions[0]?.textContent?.trim() || '';
      });
      value.value = condition.value || '';
    });
  };
  const populateFilterBuilder = (cell) => {
    if (!filterBuilder || !filterConditions) return;
    filterConditions.replaceChildren();
    const conditions = parseFilterConditions(cell.textContent);
    (conditions.length ? conditions : [{}]).forEach(addFilterCondition);
    filterBuilder.hidden = false;
  };
  const hideCellAssistance = () => {
    helper.hidden = true;
    delete helper.dataset.catalogueAssistanceField;
    helper.classList.remove('catalogue-editor-menu-open');
    helper.querySelectorAll('.searchable-select-menu, .multiselect-menu').forEach((menu) => {
      menu.style.removeProperty('position');
      menu.style.removeProperty('left');
      menu.style.removeProperty('top');
      menu.style.removeProperty('bottom');
      menu.style.removeProperty('right');
      menu.style.removeProperty('width');
      menu.style.removeProperty('max-height');
    });
  };
  const placeAssistanceMenu = (target) => {
    const shell = target.closest?.('.searchable-select-shell, .multiselect-shell');
    const menu = shell?.querySelector('.searchable-select-menu:not([hidden]), .multiselect-menu:not([hidden])');
    const editorPanel = editor.closest('.slides-templates-editor-panel');
    if (!shell || !menu || !editorPanel) return;
    const panelBounds = editorPanel.getBoundingClientRect();
    const shellBounds = shell.getBoundingClientRect();
    const gap = 7;
    // The editor panel can be taller than the viewport.  Constrain the menu
    // to the visible part of both, otherwise a fixed menu can be placed below
    // the screen and look as though it refused to open.
    const visiblePanelTop = Math.max(8, panelBounds.top);
    const visiblePanelBottom = Math.min(window.innerHeight - 8, panelBounds.bottom);
    const below = Math.max(0, visiblePanelBottom - shellBounds.bottom - gap);
    const above = Math.max(0, shellBounds.top - visiblePanelTop - gap);
    const openBelow = below >= above;
    const availableHeight = openBelow ? below : above;
    // A compact, scrollable list remains usable even when there is little
    // room beside the Cell Assistance dialog.
    const maxHeight = Math.max(96, Math.min(360, availableHeight));
    const width = Math.max(180, Math.min(shellBounds.width, panelBounds.right - shellBounds.left));
    menu.style.position = 'fixed';
    menu.style.left = `${Math.max(panelBounds.left, Math.min(shellBounds.left, panelBounds.right - width))}px`;
    menu.style.right = 'auto';
    menu.style.width = `${width}px`;
    menu.style.maxHeight = `${maxHeight}px`;
    if (openBelow) {
      menu.style.top = `${shellBounds.bottom + gap}px`;
      menu.style.bottom = 'auto';
    } else {
      menu.style.bottom = `${Math.max(0, window.innerHeight - shellBounds.top + gap)}px`;
      menu.style.top = 'auto';
    }
    helper.classList.add('catalogue-editor-menu-open');
  };
  const positionCellAssistance = (cell) => {
    helper.hidden = false;
    window.requestAnimationFrame(() => {
      const cellBounds = cell.getBoundingClientRect();
      const gap = 6;
      const helperBounds = helper.getBoundingClientRect();
      const helperWidth = helperBounds.width;
      const helperHeight = helperBounds.height;
      const cellCenterX = cellBounds.left + (cellBounds.width / 2);
      const isLeftHalf = cellCenterX < window.innerWidth / 2;
      const isTopHalf = cellBounds.top + (cellBounds.height / 2) < window.innerHeight / 2;
      // Anchor diagonally from the active cell. This keeps the source visible
      // while making the assistance panel unambiguously belong to that cell.
      let left = isLeftHalf ? cellBounds.right + gap : cellBounds.left - helperWidth - gap;
      let top = isTopHalf ? cellBounds.bottom + gap : cellBounds.top - helperHeight - gap;

      // Preserve the diagonal anchor whenever possible; only constrain it at
      // a viewport edge so the panel never becomes inaccessible.
      left = Math.min(Math.max(gap, left), window.innerWidth - helperWidth - gap);
      top = Math.min(Math.max(gap, top), window.innerHeight - helperHeight - gap);
      helper.style.left = `${left}px`;
      helper.style.top = `${top}px`;
    });
  };
  const selectCell = (cell) => {
    if (cell.getAttribute('aria-disabled') === 'true') {
      if (activeCell) activeCell.classList.remove('is-selected');
      activeCell = null;
      hideCellAssistance();
      return;
    }
    if (activeCell) activeCell.classList.remove('is-selected');
    activeCell = cell;
    activeCell.classList.add('is-selected');
    const field = cell.dataset.catalogueField || '';
    if (!assistedFields.has(field)) {
      hideCellAssistance();
      return;
    }
    helper.dataset.catalogueAssistanceField = field;
    heading.textContent = field || 'Selected cell';
    copy.textContent = helperCopy(field);
    if (labelFormatControl) labelFormatControl.hidden = field !== 'Label Format';
    if (field === 'Label Format') {
      let tokens = [];
      try { tokens = JSON.parse(cell.textContent.trim() || '[]'); } catch (_error) { tokens = []; }
      if (labelFormatColor) labelFormatColor.value = tokens.find((token) => /^#[0-9a-f]{6}$/i.test(token)) || '#FFFFFF';
      if (labelFormatColorValue) labelFormatColorValue.textContent = labelFormatColor?.value.toUpperCase() || '#FFFFFF';
      if (labelFormatFont) labelFormatFont.value = tokens.find((token) => labelFormatFont.querySelector(`option[value="${CSS.escape(token)}"]`)) || 'Arial';
      if (labelFormatSize) labelFormatSize.value = tokens.find((token) => ['Small', 'Medium', 'Large'].includes(token)) || 'Medium';
      if (labelFormatBold) labelFormatBold.checked = tokens.includes('Bold');
      if (labelFormatItalic) labelFormatItalic.checked = tokens.includes('Italic');
      if (labelFormatUnderline) labelFormatUnderline.checked = tokens.includes('Underline');
    }
    const kpiExpression = cell.textContent.trim().match(/^\s*(SUM|COUNTD|COUNT|AVERAGE|AVG|MEAN|MAX|MIN|MEDIAN)\s*\(\s*(.+?)\s*\)\s*$/i);
    if (kpiAggregationLabel) kpiAggregationLabel.hidden = field !== 'KPI';
    if (kpiAggregation) kpiAggregation.value = field === 'KPI' && kpiExpression
      ? ({AVG: 'AVERAGE', MEAN: 'AVERAGE'}[kpiExpression[1].toUpperCase()] || kpiExpression[1].toUpperCase())
      : '';
    const values = optionList(field, cell);
    const allowsMultiple = fieldColumns.has(field);
    options.multiple = allowsMultiple;
    options.size = allowsMultiple ? 11 : 1;
    options.replaceChildren();
    const existingValues = new Set(
      (allowsMultiple
        ? cell.textContent.split(groupingColumns.has(field) ? /(?:\s*×\s*|\s+[xX]\s+)/ : /\s*,\s*/)
        : [field === 'KPI' && kpiExpression ? kpiExpression[2] : cell.textContent])
        .map((value) => value.trim())
        .filter(Boolean),
    );
    const normaliseOptionValue = (value) => String(value || '')
      .trim().toLocaleLowerCase().replace(/[\s_-]+/g, ' ');
    const hasExistingValue = (value) => Array.from(existingValues).some(
      (existing) => normaliseOptionValue(existing) === normaliseOptionValue(value),
    );
    if (values.length || existingValues.size) {
      const orderedValues = [
        ...existingValues,
        ...values.filter((value) => !hasExistingValue(value)),
      ];
      orderedValues.forEach((value) => options.add(new Option(
        field === 'Legend Position' && !value ? 'No legend position' : (field === 'Label Position' && !value ? 'Automatic' : value),
        value, false, hasExistingValue(value),
      )));
      // Explicitly assign the matching value as well as marking its option.
      // This keeps the searchable single-select hydrated after it is rebuilt.
      if (!allowsMultiple) {
        const selected = Array.from(options.options).find((option) => hasExistingValue(option.value));
        options.value = selected?.value || '';
      }
    } else {
      options.add(new Option('No contextual values are defined for this field. Edit it manually.', '', true, false));
      options.options[0].disabled = true;
    }
    optionsLabel.hidden = field === 'Label Format';
    apply.hidden = values.length === 0;
    if (field === 'Filters') {
      optionsLabel.hidden = true;
      apply.hidden = true;
      populateFilterBuilder(cell);
    } else if (filterBuilder) {
      filterBuilder.hidden = true;
    }
    options.dispatchEvent(new Event('searchable-select:options-updated'));
    options.dispatchEvent(new Event('multiselect:options-updated'));
    // A preceding single-value field removes the custom control; recreate it
    // whenever this cell switches Available values back to multi-select.
    setupCustomMultiSelects();
    setupSearchableSingleSelects();
    if (!allowsMultiple) {
      window.requestAnimationFrame(() => {
        const input = options.nextElementSibling?.querySelector('.searchable-select-input');
        if (input) input.value = options.selectedOptions[0]?.textContent?.trim() || '';
      });
    }
    positionCellAssistance(cell);
  };
  const applyLabelFormat = () => {
    if (!activeCell || activeCell.dataset.catalogueField !== 'Label Format') return;
    if (labelFormatColorValue) labelFormatColorValue.textContent = labelFormatColor?.value.toUpperCase() || '#FFFFFF';
    const tokens = [labelFormatColor?.value.toUpperCase(), labelFormatFont?.value, labelFormatSize?.value, labelFormatBold?.checked && 'Bold', labelFormatItalic?.checked && 'Italic', labelFormatUnderline?.checked && 'Underline'].filter(Boolean);
    activeCell.textContent = JSON.stringify(tokens);
    refreshCellEditedState(activeCell);
  };
  [labelFormatColor, labelFormatFont, labelFormatSize, labelFormatBold, labelFormatItalic, labelFormatUnderline].forEach((control) => control?.addEventListener('input', applyLabelFormat));
  labelFormatAutomatic?.addEventListener('click', () => {
    if (!activeCell || activeCell.dataset.catalogueField !== 'Label Format') return;
    activeCell.textContent = '';
    refreshCellEditedState(activeCell);
  });
  const selectedCellFromEvent = (event) => {
    const cell = event.target.closest?.('[data-catalogue-field]');
    if (!cell) return null;
    const viewport = table.closest('.table-wrap');
    if (!viewport) return cell;
    const viewportBounds = viewport.getBoundingClientRect();
    const cellBounds = cell.getBoundingClientRect();
    const cellIsVisible = (
      cellBounds.right > viewportBounds.left
      && cellBounds.left < viewportBounds.right
      && cellBounds.bottom > viewportBounds.top
      && cellBounds.top < viewportBounds.bottom
    );
    const clickIsVisible = (
      typeof event.clientX !== 'number'
      || (
        event.clientX >= viewportBounds.left
        && event.clientX <= viewportBounds.right
        && event.clientY >= viewportBounds.top
        && event.clientY <= viewportBounds.bottom
      )
    );
    return cellIsVisible && clickIsVisible ? cell : null;
  };

  const updateRowActionStates = () => {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const blocks = [];
    rows.forEach((row) => {
      const slide = rowValue(row, 'Slide');
      if (!blocks.length || blocks.at(-1).slide !== slide) blocks.push({slide, rows: []});
      blocks.at(-1).rows.push(row);
    });
    rows.forEach((row) => {
      const block = blocks.find((item) => item.rows.includes(row));
      const rowIndex = block.rows.indexOf(row);
      const chartAction = (name) => row.querySelector(`[data-catalogue-chart-action="${name}"]`);
      if (chartAction('up')) chartAction('up').disabled = rowIndex === 0;
      if (chartAction('down')) chartAction('down').disabled = rowIndex === block.rows.length - 1;
      if (chartAction('delete')) chartAction('delete').disabled = rows.length <= 1;
    });
    blocks.forEach((block, index) => {
      const action = (name) => block.rows[0].querySelector(`[data-catalogue-slide-action="${name}"]`);
      if (action('up')) action('up').disabled = index === 0;
      if (action('down')) action('down').disabled = index === blocks.length - 1;
      if (action('delete')) action('delete').disabled = blocks.length <= 1;
    });
  };
  const sharedSlideFields = ['Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout'];
  const sharedValueKey = (field) => `catalogueShared${field.replace(/[^a-z0-9]+/gi, '')}`;
  const rowValue = (row, field) => {
    const value = row.querySelector(`[data-catalogue-field="${field}"]`)?.textContent.trim()
      ?? row.dataset[sharedValueKey(field)]
      ?? '';
    return field === 'Filters' ? canonicalFilterValue(value) : value;
  };
  const syncConditionalVisualCells = (row, {clear = true} = {}) => {
    if (!row) return;
    const applicability = {
      'Axis X Range': true,
      'Axis Y Range': true,
      'Label Position': true,
      'Label Format': true,
    };
    Object.entries(applicability).forEach(([field, enabled]) => {
      const cell = row.querySelector(`[data-catalogue-field="${field}"]`);
      if (!cell) return;
      if (!enabled && clear && cell.textContent.trim()) cell.textContent = '';
      cell.contentEditable = enabled ? 'true' : 'false';
      cell.setAttribute('aria-disabled', String(!enabled));
      cell.classList.toggle('is-inapplicable', !enabled);
      cell.title = enabled ? '' : `${field} is not available for this chart type.`;
      refreshCellEditedState(cell);
    });
  };
  const rowValues = (row) => {
    const values = Object.fromEntries(catalogueHeaders.map((header) => [header, rowValue(row, header)]));
    values.__editedFields = Array.from(row.querySelectorAll('[data-catalogue-field].is-edited'))
      .map((cell) => cell.dataset.catalogueField);
    values.__originalValues = Object.fromEntries(catalogueHeaders.map((header) => {
      const cell = row.querySelector(`[data-catalogue-field="${header}"]`);
      return [header, cell?.dataset.originalValue ?? rowValue(row, header)];
    }));
    return values;
  };
  const createActionButton = (label, action, title, kind, className = '') => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.dataset[kind === 'slide' ? 'catalogueSlideAction' : 'catalogueChartAction'] = action;
    button.title = title;
    button.setAttribute('aria-label', title);
    if (className) button.className = className;
    return button;
  };
  const actionButtons = (kind, hasSource = false) => {
    const subject = kind === 'slide' ? 'slide' : 'chart';
    return [
      createActionButton('↑', 'up', `Move ${subject} up`, kind),
      createActionButton('↓', 'down', `Move ${subject} down`, kind),
      createActionButton('+', 'insert', `Insert ${subject} below`, kind),
      createActionButton('−', 'delete', `Delete ${subject}`, kind, 'catalogue-row-delete'),
      createActionButton('⧉', 'duplicate', `Duplicate ${subject}`, kind),
      createActionButton('⇥', 'export', `Copy ${subject} to a template`, kind),
      ...(kind === 'chart' && hasSource ? [
        createActionButton('▥', 'preview', 'Preview chart data', kind),
        createActionButton('👁', 'chart-preview', 'Preview generated chart', kind),
      ] : []),
    ];
  };
  const actionButtonRows = (kind, hasSource = false) => {
    const buttons = actionButtons(kind, hasSource);
    const primary = document.createElement('div');
    primary.className = 'catalogue-action-row catalogue-action-row-primary';
    primary.append(...buttons.slice(0, 4));
    const secondary = document.createElement('div');
    secondary.className = 'catalogue-action-row catalogue-action-row-secondary';
    secondary.append(...buttons.slice(4));
    return [primary, secondary];
  };
  const createCatalogueRow = (sourceRow, blankChartFields = false) => {
    const source = sourceRow instanceof HTMLTableRowElement ? rowValues(sourceRow) : (sourceRow || {});
    const retained = ['Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout'];
    const row = document.createElement('tr');
    const slideActions = document.createElement('td');
    slideActions.className = 'catalogue-slide-actions';
    slideActions.dataset.catalogueSlideActions = '';
    row.append(slideActions);
    catalogueHeaders.forEach((header) => {
      if (header === 'Chart Tittle') {
        const chartActions = document.createElement('td');
        chartActions.className = 'catalogue-chart-actions';
        chartActions.dataset.catalogueChartActions = '';
        chartActions.append(...actionButtonRows('chart', Boolean(String(source['CDR source'] || '').trim())));
        row.append(chartActions);
      }
      const cell = document.createElement('td');
      cell.contentEditable = 'true';
      cell.spellcheck = false;
      cell.dataset.catalogueField = header;
      // Only a newly inserted sibling starts with blank chart fields. Rows
      // rebuilt for grouping, sorting or saving must retain every definition.
      const value = blankChartFields && !retained.includes(header) ? '' : (source[header] || '');
      const originalValue = source.__originalValues?.[header] ?? value;
      cell.dataset.originalValue = originalValue;
      if (header === 'Filters') renderFilterCell(cell, value, source.__editedFields?.includes(header) ? originalValue : null);
      else if (source.__editedFields?.includes(header)) renderAddedText(cell, value, originalValue);
      else cell.textContent = value;
      if (source.__editedFields?.includes(header)) cell.classList.add('is-edited');
      row.append(cell);
    });
    syncConditionalVisualCells(row);
    return row;
  };
  const sortCatalogueRows = (rows) => rows.map((row, position) => {
    const slide = Number(row.Slide);
    return {row, position, slide: Number.isInteger(slide) && slide > 0 ? slide : null};
  }).sort((left, right) => {
    if (left.slide === null && right.slide === null) return left.position - right.position;
    if (left.slide === null) return 1;
    if (right.slide === null) return -1;
    return left.slide - right.slide || left.position - right.position;
  }).map(({row}) => row);
  const mergeSlideMetadataCells = () => {
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    let start = 0;
    let slideBlockIndex = 0;
    while (start < rows.length) {
      const slide = rowValue(rows[start], 'Slide');
      let end = start + 1;
      while (end < rows.length && rowValue(rows[end], 'Slide') === slide) end += 1;
      const block = rows.slice(start, end);
      const tone = slideBlockIndex % 2 === 0 ? 'catalogue-slide-tone-purple' : 'catalogue-slide-tone-pink';
      block.forEach((row) => row.classList.add(tone));
      const slideActions = block[0].querySelector('[data-catalogue-slide-actions]');
      if (slideActions) {
        slideActions.replaceChildren(...actionButtonRows('slide'));
        slideActions.rowSpan = block.length;
      }
      block.slice(1).forEach((row) => row.querySelector('[data-catalogue-slide-actions]')?.remove());
      if (slide && block.length > 1) {
        sharedSlideFields.forEach((field) => {
          const master = block[0].querySelector(`[data-catalogue-field="${field}"]`);
          if (!master) return;
          const value = master.textContent.trim();
          const key = sharedValueKey(field);
          block.forEach((row) => { row.dataset[key] = value; });
          master.rowSpan = block.length;
          master.classList.add('catalogue-shared-slide-cell');
          master.addEventListener('input', () => {
            block.forEach((row) => { row.dataset[key] = master.textContent.trim(); });
          });
          block.slice(1).forEach((row) => row.querySelector(`[data-catalogue-field="${field}"]`)?.remove());
        });
      }
      start = end;
      slideBlockIndex += 1;
    }
  };
  const renderCatalogueRows = (rows) => {
    const body = table.querySelector('tbody');
    if (!body) return;
    // Do not pass createCatalogueRow directly to map: map also supplies the
    // row index, which must never be interpreted as blankChartFields.
    const renderedRows = sortCatalogueRows(rows).map((row) => createCatalogueRow(row));
    renderedRows.forEach((row, index) => { row.dataset.catalogueRowIndex = String(index); });
    body.replaceChildren(...renderedRows);
    mergeSlideMetadataCells();
    updateRowActionStates();
  };
  const normaliseCatalogueRows = () => {
    const body = table.querySelector('tbody');
    if (!body) return;
    renderCatalogueRows(Array.from(body.querySelectorAll('tr')).map(rowValues));
  };
  const serialiseCatalogueContent = () => {
    const escapeCsv = (value, preserveLineBreaks = false) => {
      const text = preserveLineBreaks ? String(value || '') : String(value || '').replace(/\r?\n/g, '\\n');
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    normaliseCatalogueRows();
    const rows = Array.from(table.querySelectorAll('tbody tr')).map((row) => (
      catalogueHeaders.map((header) => {
        const value = rowValue(row, header);
        return escapeCsv(header === 'Filters' ? displayedFilterValue(value) : value, header === 'Filters');
      }).join(',')
    ));
    return [catalogueHeaders.map(escapeCsv).join(','), ...rows].join('\n');
  };
  let savedCatalogueContent = '';
  const hasUnsavedCatalogueChanges = () => serialiseCatalogueContent() !== savedCatalogueContent;
  const acceptCurrentCatalogueAsBaseline = () => {
    table.querySelectorAll('[data-catalogue-field]').forEach((cell) => {
      const field = cell.dataset.catalogueField || '';
      const current = rowValue(cell.closest('tr'), field);
      cell.dataset.originalValue = current;
      cell.classList.remove('is-edited');
      if (field === 'Filters') renderFilterCell(cell, current);
      else cell.textContent = current;
    });
  };
  const renderChartPreview = (payload) => {
    if (!chartPreview || !chartPreviewTable || !chartPreviewTitle || !chartPreviewSummary) return;
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const columns = Array.isArray(payload.summary?.columns) ? payload.summary.columns : [];
    chartPreviewTitle.textContent = `${payload.chart_title || 'Selected chart'} · ${payload.source || ''}`;
    chartPreviewSummary.textContent = `${payload.summary?.matched_rows ?? 0} matching rows from ${payload.summary?.source_rows ?? 0}; showing ${payload.summary?.shown_rows ?? 0}. Filters: ${payload.filters || 'No filters'}.`;
    chartPreviewTableWrap?.removeAttribute('hidden');
    if (chartPreviewImageUrl) { URL.revokeObjectURL(chartPreviewImageUrl); chartPreviewImageUrl = ''; }
    if (chartPreviewImageContent) chartPreviewImageContent.removeAttribute('src');
    if (chartPreviewImage) chartPreviewImage.hidden = true;
    if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
    chartPreviewTable.innerHTML = columns.length
      ? `<thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map((item) => `<tr>${columns.map((column) => `<td>${escapeHtml(item[column])}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${columns.length}">No rows match this chart definition.</td></tr>`}</tbody>`
      : '<tbody><tr><td>No chart fields are available to preview.</td></tr></tbody>';
    chartPreview.hidden = false;
  };
  const closeChartPreview = () => { if (chartPreview) chartPreview.hidden = true; };
  chartPreviewClose?.addEventListener('click', closeChartPreview);
  chartPreviewActionClose?.addEventListener('click', closeChartPreview);
  chartPreview?.addEventListener('click', (event) => { if (event.target === chartPreview) closeChartPreview(); });
  const previewChartData = async (row, definition = {}) => {
    const endpoint = editor.dataset.chartPreviewUrl;
    if (!endpoint) return;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(row);
    if (rowIndex < 0) return;
    const button = row.querySelector('[data-catalogue-chart-action="preview"]');
    if (button) button.disabled = true;
    showLoadingOverlay('Generating Chart Data Preview', 'Please wait while the Chart Data Preview is generated.');
    try {
      const response = await fetch(endpoint, {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({catalogue_content: serialiseCatalogueContent(), row_index: rowIndex, definition}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to preview chart data.');
      renderChartPreview(payload);
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to preview chart data.', {title: 'Chart Data Preview', tone: 'error'});
    } finally {
      hideLoadingOverlay();
      if (button) button.disabled = false;
    }
  };
  const previewDefinition = () => Object.fromEntries(Array.from(chartPreviewFields?.querySelectorAll('[name]') || []).map((control) => {
    if (!control.multiple) {
      if (control.name === 'kpi') {
        const operation = chartPreviewFields?.querySelector('[data-preview-kpi-aggregation]')?.value || '';
        return [control.name, operation && control.value ? `${operation}(${control.value})` : control.value];
      }
      return [control.name, control.value];
    }
    const separator = control.name === 'legend' ? ', ' : ' × ';
    return [control.name, Array.from(control.selectedOptions).map((option) => option.value).filter(Boolean).join(separator)];
  }));
  const previewDefinitionFromRow = (row) => ({
    chart_type: rowValue(row, 'Chart type'), chart_title: rowValue(row, 'Chart Tittle'), cdr_source: rowValue(row, 'CDR source'),
    kpi: rowValue(row, 'KPI'), filters: rowValue(row, 'Filters'), grouping_rows: rowValue(row, 'Rows Aggregation'),
    grouping_columns: rowValue(row, 'Column Aggregation'), legend: rowValue(row, 'Legend'), legend_position: rowValue(row, 'Legend Position'),
    axis_x_range: rowValue(row, 'Axis X Range'), axis_y_range: rowValue(row, 'Axis Y Range'),
    label_position: rowValue(row, 'Label Position'),
    label_format: rowValue(row, 'Label Format'),
    exclude_null_empty: rowValue(row, 'Exclude Null/Empty'), exclude_zero: rowValue(row, 'Exclude Zero'),
  });
  const renderChartPreviewSandbox = (row, definition = null) => {
    if (!chartPreviewSandbox || !chartPreviewFields) return;
    const current = definition || previewDefinitionFromRow(row);
    const regenerate = () => {
      if (chartPreviewTimer) window.clearTimeout(chartPreviewTimer);
      chartPreviewController?.abort();
      chartPreviewTimer = window.setTimeout(() => previewGeneratedChart(row, previewDefinition(), false), 350);
    };
    createInteractiveChartPreviewControls(chartPreviewFields, current, {
      columnsBySource: suggestions.columns,
      fields: [
        ['chart_type', 'Chart Type'], ['chart_title', 'Chart Tittle'], ['cdr_source', 'CDR Source'], ['kpi', 'KPI'], ['filters', 'Filters'],
        ['grouping_rows', 'Rows'], ['grouping_columns', 'Columns'], ['legend', 'Legend'], ['legend_position', 'Legend Position'],
        ['axis_x_range', 'Axis X Range'], ['axis_y_range', 'Axis Y Range'],
        ['label_position', 'Label Position'], ['label_format', 'Label Format'], ['exclude_null_empty', 'Exclude Null/Empty'], ['exclude_zero', 'Exclude Zero'],
      ],
      textFields: {chart_title: true},
      // Keep these option sets identical to the persisted Chart Viewer.
      chartTypes: ['100% Stacked Vertical Bars', 'Count Stacked Horizontal Bars', 'CDF Line', 'Multi KPI CDF Lines', 'Scatter', 'Table', 'Dynamic Table', 'Distribution Stacked Vertical Bars', 'Threshold Stacked Vertical Bars', 'Average Vertical Bars', 'Median Vertical Bars', 'Map'],
      cdrSources: ['CDR-Data', 'CDR-Voice', 'CDR-Speech'],
      legendPositions: ['', 'Top', 'Bottom', 'Left', 'Right'],
      labelPositions: ['', 'None', 'Top', 'Up', 'Middle', 'Down'],
      onChange: regenerate,
      onSourceChange: (next) => {
        renderChartPreviewSandbox(row, next);
        regenerate();
      },
    });
    chartPreviewSandbox.hidden = false;
  };
  const previewGeneratedChart = async (row, definition = {}, showOverlay = true) => {
    const endpoint = editor.dataset.chartImagePreviewUrl;
    if (!endpoint) return;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(row);
    if (rowIndex < 0) return;
    // serialiseCatalogueContent normalises/rebuilds editor rows. Resolve the
    // authoritative replacement row immediately afterwards, then initialise
    // the preview from those values rather than the stale click target.
    const catalogueContent = serialiseCatalogueContent();
    const resolvedRow = Array.from(table.querySelectorAll('tbody tr'))[rowIndex] || row;
    const rowDefinition = {...previewDefinitionFromRow(resolvedRow), ...definition};
    const button = row.querySelector('[data-catalogue-chart-action="chart-preview"]');
    if (button) button.disabled = true;
    const requestId = ++chartPreviewRequest;
    chartPreviewController?.abort();
    chartPreviewController = new AbortController();
    if (showOverlay) showLoadingOverlay('Generating Chart Preview', 'Please wait while the chart preview is generated.');
    try {
      const response = await fetch(endpoint, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, signal: chartPreviewController.signal, body: JSON.stringify({catalogue_content: catalogueContent, row_index: rowIndex, definition: rowDefinition})});
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Unable to preview the generated chart.');
      }
      const image = await response.blob();
      if (requestId !== chartPreviewRequest) return;
      if (chartPreviewImageUrl) URL.revokeObjectURL(chartPreviewImageUrl);
      chartPreviewImageUrl = URL.createObjectURL(image);
      if (chartPreviewImageContent) chartPreviewImageContent.src = chartPreviewImageUrl;
      if (chartPreviewImage) chartPreviewImage.hidden = false;
      if (chartPreviewTableWrap) chartPreviewTableWrap.hidden = true;
      if (chartPreviewTitle) chartPreviewTitle.textContent = `Generated chart preview · ${rowDefinition.chart_title || rowValue(row, 'Slide Tittle') || 'Selected chart'}`;
      if (chartPreviewSummary) chartPreviewSummary.textContent = 'This is the chart image produced by the current unsaved template definition.';
      if (showOverlay) {
        chartPreviewDialog?.classList.remove('is-dataset-only');
        chartPreviewRow = resolvedRow;
        renderChartPreviewSandbox(chartPreviewRow, rowDefinition);
      }
      if (chartPreview) chartPreview.hidden = false;
    } catch (error) {
      if (error.name !== 'AbortError') showInfoDialog(error instanceof Error ? error.message : 'Unable to preview the generated chart.', {title: 'Generated Chart Preview', tone: 'error'});
    } finally {
      if (showOverlay) hideLoadingOverlay();
      if (button) button.disabled = false;
    }
  };
  chartPreviewUpdate?.addEventListener('click', async () => {
    if (!chartPreviewRow) return;
    const chartName = rowValue(chartPreviewRow, 'Chart Tittle') || rowValue(chartPreviewRow, 'Slide Tittle') || 'the displayed chart';
    const accepted = await showConfirmDialog(
      `Warning: the template row for '${chartName}' will be updated with the values configured in the Interactive Preview panel. Continue?`,
      {title: 'Update Template?', confirmLabel: 'Update Template', tone: 'warning'},
    );
    if (!accepted) return;
    const mapping = {chart_title: 'Chart Tittle', chart_type: 'Chart type', cdr_source: 'CDR source', kpi: 'KPI', filters: 'Filters', grouping_rows: 'Rows Aggregation', grouping_columns: 'Column Aggregation', legend: 'Legend', legend_position: 'Legend Position', label_position: 'Label Position', label_format: 'Label Format', axis_x_range: 'Axis X Range', axis_y_range: 'Axis Y Range', exclude_null_empty: 'Exclude Null/Empty', exclude_zero: 'Exclude Zero'};
    Object.entries(previewDefinition()).forEach(([key, value]) => {
      const cell = Array.from(chartPreviewRow.querySelectorAll('[data-catalogue-field]')).find((item) => item.dataset.catalogueField === mapping[key]);
      if (!cell) return;
      if (mapping[key] === 'Filters') renderFilterCell(cell, value);
      else cell.textContent = value;
      refreshCellEditedState(cell);
      if (cell.classList.contains('is-edited')) {
        if (mapping[key] === 'Filters') renderFilterCell(cell, value, cell.dataset.originalValue || '');
        else { cell.replaceChildren(); renderAddedText(cell, value, cell.dataset.originalValue || ''); }
      }
    });
    syncConditionalVisualCells(chartPreviewRow);
    showInfoDialog('The current preview values have been applied to this template row. Save the template to persist them.', {title: 'Template updated'});
  });
  chartPreviewData?.addEventListener('click', async () => {
    if (!chartPreviewRow) return;
    const endpoint = editor.dataset.chartPreviewUrl;
    const rowIndex = Array.from(table.querySelectorAll('tbody tr')).indexOf(chartPreviewRow);
    if (!endpoint || rowIndex < 0 || !chartPreviewDataPanel) return;
    chartPreviewData.disabled = true;
    showLoadingOverlay('Loading Filtered Dataset', 'Please wait while the filtered dataset is prepared.');
    try {
      const activeDefinition = chartPreviewSandbox && !chartPreviewSandbox.hidden ? previewDefinition() : {};
      const requestPage = async ({page = 0, column_filters = {}, filter_column = null} = {}) => {
        const response = await fetch(endpoint, {
          method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            catalogue_content: serialiseCatalogueContent(), row_index: rowIndex,
            definition: activeDefinition, page, page_size: chartPreviewDatasetPageSize,
            column_filters, filter_column,
          }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'Unable to load filtered dataset.');
        return payload;
      };
      const payload = await requestPage();
      const exportRequest = async ({column_filters = {}} = {}) => {
        const response = await fetch(endpoint, {
          method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            catalogue_content: serialiseCatalogueContent(), row_index: rowIndex,
            definition: activeDefinition, column_filters, download: true,
          }),
        });
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => ({}));
          throw new Error(errorPayload.detail || 'Unable to export the filtered dataset.');
        }
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = url; link.download = 'filtered-chart-dataset.csv';
        document.body.append(link); link.click(); link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      window.createUnifiedDatasetViewer({
        host: chartPreviewDataPanel, payload, requestPage,
        exportControl: chartPreviewDataExport, exportRequest,
      });
      if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
      if (chartPreview) chartPreview.hidden = false;
      if (chartPreviewDataOverlay) chartPreviewDataOverlay.hidden = false;
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'Unable to load filtered dataset.', {title: 'Filtered dataset', tone: 'error'});
    } finally {
      hideLoadingOverlay();
      chartPreviewData.disabled = false;
    }
  });
  const closeChartPreviewData = (restoreFocus = false) => {
    if (!chartPreviewDataOverlay) return;
    chartPreviewDataOverlay.hidden = true;
    if (chartPreviewDialog?.classList.contains('is-dataset-only')) {
      chartPreviewDialog.classList.remove('is-dataset-only');
      if (chartPreview) chartPreview.hidden = true;
    } else if (chartPreviewSandbox) chartPreviewSandbox.hidden = false;
    if (restoreFocus) chartPreviewData?.focus();
  };
  chartPreviewDataOverlay?.addEventListener('click', (event) => {
    if (event.target === chartPreviewDataOverlay || event.target.closest('[data-catalogue-chart-preview-data-close]')) closeChartPreviewData(true);
  });
  window.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !chartPreviewDataOverlay || chartPreviewDataOverlay.hidden) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    closeChartPreviewData(true);
  }, true);
  const catalogueBlocks = () => {
    const blocks = [];
    Array.from(table.querySelectorAll('tbody tr')).map(rowValues).forEach((values) => {
      if (!blocks.length || blocks.at(-1).slide !== values.Slide) blocks.push({slide: values.Slide, rows: []});
      blocks.at(-1).rows.push(values);
    });
    return blocks;
  };
  const markCopiedRow = (values) => ({
    ...values,
    __editedFields: [...catalogueHeaders],
    __originalValues: Object.fromEntries(catalogueHeaders.map((header) => [header, ''])),
  });
  const renumberBlocks = (blocks) => blocks.flatMap((block, index) => block.rows.map((values) => {
    const slide = String(index + 1);
    const edited = new Set(values.__editedFields || []);
    if (String(values.Slide || '') !== slide) edited.add('Slide');
    return {...values, Slide: slide, __editedFields: [...edited]};
  }));
  const showCatalogueExportDialog = (kind, templates, sourceBlocks) => new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay catalogue-copy-overlay';
    const panel = document.createElement('section');
    panel.className = 'confirm-panel catalogue-copy-dialog';
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    const eyebrow = document.createElement('p'); eyebrow.className = 'eyebrow'; eyebrow.textContent = 'Copy template content';
    const title = document.createElement('h3'); title.textContent = `Copy ${kind === 'slide' ? 'slide' : kind === 'chart' ? 'chart' : 'auto-calculated field'} to template`;
    const form = document.createElement('div'); form.className = 'catalogue-copy-fields';
    const createField = (labelText) => {
      const field = document.createElement('label'); field.textContent = labelText;
      const select = document.createElement('select'); field.append(select); form.append(field);
      return {field, select};
    };
    const destination = createField('Destination template');
    templates.forEach((item) => destination.select.add(new Option(`${item.technology.toUpperCase()} · ${item.name}`, `${item.technology}:${item.identifier}`)));
    const slidePosition = createField('Slide position');
    const destinationSlide = createField('Destination slide');
    const chartPosition = createField('Chart position');
    slidePosition.field.hidden = kind !== 'slide';
    destinationSlide.field.hidden = kind !== 'chart';
    chartPosition.field.hidden = kind !== 'chart';
    const actions = document.createElement('div'); actions.className = 'confirm-actions';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary-button'; cancel.textContent = 'Cancel';
    const accept = document.createElement('button'); accept.type = 'button'; accept.textContent = 'Copy';
    actions.append(cancel, accept); panel.append(eyebrow, title, form, actions); overlay.append(panel); document.body.append(overlay);
    const selectedTemplate = () => {
      const [technology, identifier] = destination.select.value.split(':', 2);
      return {technology, identifier, sameTemplate: technology === editor.dataset.templateTechnology && identifier === editor.dataset.templateIdentifier};
    };
    const selectedSlides = () => {
      const selected = selectedTemplate();
      if (selected.sameTemplate) return sourceBlocks.map((block, index) => ({title: block.rows[0]['Slide Tittle'] || `Slide ${index + 1}`, charts: block.rows.length}));
      return templates.find((item) => item.technology === selected.technology && item.identifier === selected.identifier)?.slides || [];
    };
    const updateChartPositions = () => {
      const slides = selectedSlides();
      const selectedIndex = Number(destinationSlide.select.value || 0);
      const chartCount = Number(slides[selectedIndex]?.charts || 0);
      chartPosition.select.replaceChildren(...Array.from({length: chartCount + 1}, (_, index) => new Option(
        index < chartCount ? `Before chart ${index + 1}` : (chartCount ? `After chart ${chartCount}` : 'Chart 1'), String(index),
      )));
    };
    const updateDestinationFields = () => {
      const slides = selectedSlides();
      if (kind === 'dimension') {
        accept.disabled = false;
        return;
      }
      if (kind === 'slide') {
        slidePosition.select.replaceChildren(...Array.from({length: slides.length + 1}, (_, index) => new Option(
          index < slides.length ? `Before slide ${index + 1} · ${slides[index].title}` : (slides.length ? `After slide ${slides.length}` : 'Slide 1'), String(index),
        )));
        accept.disabled = false;
        return;
      }
      destinationSlide.select.replaceChildren(...slides.map((item, index) => new Option(`Slide ${index + 1} · ${item.title}`, String(index))));
      accept.disabled = slides.length === 0;
      updateChartPositions();
    };
    const finish = (value) => { overlay.remove(); resolve(value); };
    destination.select.addEventListener('change', updateDestinationFields);
    destinationSlide.select.addEventListener('change', updateChartPositions);
    cancel.addEventListener('click', () => finish(null));
    accept.addEventListener('click', () => {
      const selected = selectedTemplate();
      finish({
        targetTechnology: selected.technology,
        targetIdentifier: selected.identifier,
        sameTemplate: selected.sameTemplate,
        slidePosition: Number(slidePosition.select.value || 0),
        targetSlideIndex: Number(destinationSlide.select.value || 0),
        chartPosition: Number(chartPosition.select.value || 0),
      });
    });
    overlay.addEventListener('click', (event) => { if (event.target === overlay) finish(null); });
    accept.disabled = templates.length === 0;
    if (templates.length) updateDestinationFields();
    destination.select.focus();
  });
  const exportCatalogueItem = async (kind, rowIndex) => {
    const sourceBlocks = catalogueBlocks();
    const sourceRow = Array.from(table.querySelectorAll('tbody tr'))[rowIndex];
    const sourceSlide = rowValue(sourceRow, 'Slide');
    const sourceBlockIndex = sourceBlocks.findIndex((block) => block.slide === sourceSlide);
    showLoadingOverlay('Loading Report Templates', 'Please wait while the available destinations are loaded.');
    try {
      const response = await fetch(editor.dataset.templateOptionsUrl, {credentials: 'same-origin'});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to load Report Templates.');
      hideLoadingOverlay();
      const templates = Array.isArray(payload.templates) ? payload.templates : [];
      const selection = await showCatalogueExportDialog(kind, templates, sourceBlocks);
      if (!selection) return;
      if (kind === 'slide' && selection.sameTemplate) {
        const copied = {slide: '', rows: sourceBlocks[sourceBlockIndex].rows.map(markCopiedRow)};
        sourceBlocks.splice(selection.slidePosition, 0, copied);
        renderCatalogueRows(renumberBlocks(sourceBlocks));
        return;
      }
      if (kind === 'chart' && selection.sameTemplate) {
        const flatRows = Array.from(table.querySelectorAll('tbody tr'));
        const copied = markCopiedRow(rowValues(flatRows[rowIndex]));
        const targetBlock = sourceBlocks[selection.targetSlideIndex];
        sharedSlideFields.forEach((field) => { copied[field] = targetBlock.rows[0][field]; });
        targetBlock.rows.splice(selection.chartPosition, 0, copied);
        renderCatalogueRows(renumberBlocks(sourceBlocks));
        return;
      }
      showLoadingOverlay(`Copying ${kind}`, 'Please wait while the destination template is updated.');
      const requestPayload = {
        kind,
        catalogue_content: serialiseCatalogueContent(),
        source_row_index: rowIndex,
        target_technology: selection.targetTechnology,
        target_identifier: selection.targetIdentifier,
        ...(kind === 'slide' ? {slide_position: selection.slidePosition} : {target_slide_index: selection.targetSlideIndex, chart_position: selection.chartPosition}),
      };
      const copyResponse = await fetch(editor.dataset.templateCopyUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(requestPayload)});
      const result = await copyResponse.json().catch(() => ({}));
      if (!copyResponse.ok) throw new Error(result.detail || `Unable to copy the ${kind}.`);
      hideLoadingOverlay();
      showInfoDialog(`The ${kind} was copied to the selected Report Template.`, {title: 'Template content copied'});
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'Unable to copy template content.', {title: 'Copy template content', tone: 'error'});
    }
  };
  const clearActiveCellForRows = (rows) => {
    if (!activeCell || !rows.includes(activeCell.closest('tr'))) return;
    activeCell.classList.remove('is-selected'); activeCell = null;
    heading.textContent = 'Select a cell';
    copy.textContent = 'Select a table cell to see compatible layouts, chart types or processed CDR columns.';
    optionsLabel.hidden = true; apply.hidden = true;
    if (filterBuilder) filterBuilder.hidden = true;
  };
  table.addEventListener('click', async (event) => {
    const button = event.target.closest?.('[data-catalogue-chart-action], [data-catalogue-slide-action]');
    if (!button) return;
    event.preventDefault();
    const row = button.closest('tr');
    if (!row) return;
    const kind = button.dataset.catalogueSlideAction !== undefined ? 'slide' : 'chart';
    const action = kind === 'slide' ? button.dataset.catalogueSlideAction : button.dataset.catalogueChartAction;
    const flatRows = Array.from(table.querySelectorAll('tbody tr'));
    const rowIndex = flatRows.indexOf(row);
    if (action === 'preview') {
      chartPreviewRow = row;
      chartPreviewDialog?.classList.add('is-dataset-only');
      if (chartPreviewTitle) chartPreviewTitle.textContent = `Filtered dataset · ${rowValue(row, 'Chart Tittle') || rowValue(row, 'Slide Tittle') || 'Selected chart'}`;
      if (chartPreviewSummary) chartPreviewSummary.textContent = 'The complete chart-filtered dataset is available in paginated pages.';
      if (chartPreviewImage) chartPreviewImage.hidden = true;
      if (chartPreviewSandbox) chartPreviewSandbox.hidden = true;
      if (chartPreviewTableWrap) chartPreviewTableWrap.hidden = true;
      showLoadingOverlay('Loading Chart Data Preview', 'Please wait while the selected chart dataset is loaded.');
      chartPreviewData?.click(); return;
    }
    if (action === 'chart-preview') { await previewGeneratedChart(row); return; }
    if (action === 'export') { await exportCatalogueItem(kind, rowIndex); return; }
    const blocks = catalogueBlocks();
    const slide = rowValue(row, 'Slide');
    const blockIndex = blocks.findIndex((block) => block.slide === slide);
    const chartIndex = blocks[blockIndex].rows.findIndex((_item, index) => flatRows.filter((candidate) => rowValue(candidate, 'Slide') === slide)[index] === row);
    if (kind === 'chart') {
      const charts = blocks[blockIndex].rows;
      if (action === 'up' && chartIndex > 0) [charts[chartIndex - 1], charts[chartIndex]] = [charts[chartIndex], charts[chartIndex - 1]];
      else if (action === 'down' && chartIndex < charts.length - 1) [charts[chartIndex], charts[chartIndex + 1]] = [charts[chartIndex + 1], charts[chartIndex]];
      else if (action === 'insert') charts.splice(chartIndex + 1, 0, {...charts[chartIndex], ...Object.fromEntries(catalogueHeaders.filter((header) => !sharedSlideFields.includes(header)).map((header) => [header, ''])), __editedFields: [...catalogueHeaders.filter((header) => !sharedSlideFields.includes(header))]});
      else if (action === 'duplicate') charts.splice(chartIndex + 1, 0, markCopiedRow({...charts[chartIndex]}));
      else if (action === 'delete') { clearActiveCellForRows([row]); charts.splice(chartIndex, 1); if (!charts.length) blocks.splice(blockIndex, 1); }
    } else {
      if (action === 'up' && blockIndex > 0) [blocks[blockIndex - 1], blocks[blockIndex]] = [blocks[blockIndex], blocks[blockIndex - 1]];
      else if (action === 'down' && blockIndex < blocks.length - 1) [blocks[blockIndex], blocks[blockIndex + 1]] = [blocks[blockIndex + 1], blocks[blockIndex]];
      else if (action === 'insert') blocks.splice(blockIndex + 1, 0, {slide: '', rows: [markCopiedRow(Object.fromEntries(catalogueHeaders.map((header) => [header, ''])))]});
      else if (action === 'duplicate') blocks.splice(blockIndex + 1, 0, {slide: '', rows: blocks[blockIndex].rows.map((item) => markCopiedRow({...item}))});
      else if (action === 'delete') { clearActiveCellForRows(flatRows.filter((candidate) => rowValue(candidate, 'Slide') === slide)); blocks.splice(blockIndex, 1); }
    }
    if (!blocks.length) blocks.push({slide: '1', rows: [Object.fromEntries(catalogueHeaders.map((header) => [header, header === 'Slide' ? '1' : '']))]});
    renderCatalogueRows(renumberBlocks(blocks));
  });
  normaliseCatalogueRows();
  const focusCatalogueRow = (rowIndex) => {
    if (!Number.isInteger(rowIndex) || rowIndex < 0) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const row = table.querySelector(`tbody tr[data-catalogue-row-index="${rowIndex}"]`);
      const viewport = table.closest('.table-wrap');
      if (!row || !viewport) return;
      row.classList.add('catalogue-editor-focus-row');
      viewport.scrollTop = Math.max(0, row.offsetTop - (viewport.clientHeight - row.offsetHeight) / 2);
      const chartTitle = row.querySelector('[data-catalogue-field="Chart Tittle"]');
      if (chartTitle) viewport.scrollLeft = Math.max(0, chartTitle.offsetLeft - viewport.clientWidth / 3);
      (chartTitle || row.querySelector('[data-catalogue-field="Slide Tittle"]'))?.focus({preventScroll: true});
    }));
  };
  focusCatalogueRow(requestedRowIndex);
  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || event.data?.type !== 'dashboard-analytic:focus-template-row') return;
    focusCatalogueRow(Number(event.data.row));
  });
  reenumerate?.addEventListener('click', () => {
    const body = table.querySelector('tbody');
    if (!body) return;
    const rows = Array.from(body.querySelectorAll('tr')).map((row, position) => {
      const value = rowValue(row, 'Slide');
      const parsed = Number(value);
      return {
        row,
        position,
        slide: Number.isInteger(parsed) && parsed > 0 ? parsed : null,
      };
    });
    rows.sort((left, right) => {
      if (left.slide === null && right.slide === null) return left.position - right.position;
      if (left.slide === null) return 1;
      if (right.slide === null) return -1;
      return left.slide - right.slide || left.position - right.position;
    });
    const reenumeratedSlides = new Map();
    let nextSlide = 1;
    rows.forEach(({ row, slide }) => {
      body.append(row);
      if (slide === null) return;
      if (!reenumeratedSlides.has(slide)) {
        reenumeratedSlides.set(slide, nextSlide);
        nextSlide += 1;
      }
      const reenumerated = String(reenumeratedSlides.get(slide));
      row.dataset[sharedValueKey('Slide')] = reenumerated;
      const slideCell = row.querySelector('[data-catalogue-field="Slide"]');
      if (slideCell) { slideCell.textContent = reenumerated; refreshCellEditedState(slideCell); }
    });
    normaliseCatalogueRows();
  });
  table.addEventListener('focusin', (event) => {
    const cell = selectedCellFromEvent(event);
    if (cell) selectCell(cell);
  });
  table.addEventListener('click', (event) => {
    const cell = selectedCellFromEvent(event);
    if (cell) selectCell(cell);
  });
  table.addEventListener('input', (event) => {
    const cell = event.target.closest?.('[data-catalogue-field]');
    refreshCellEditedState(cell);
    if (cell?.dataset.catalogueField === 'Chart type') syncConditionalVisualCells(cell.closest('tr'));
    if (cell?.dataset.catalogueField === 'Filters') refreshFilterValidationAlert();
  });
  document.addEventListener('pointerdown', (event) => {
    if (!selectedCellFromEvent(event) && !helper.contains(event.target)) hideCellAssistance();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || helper.hidden) return;
    event.preventDefault();
    hideCellAssistance();
    activeCell?.blur();
  });
  table.closest('.table-wrap')?.addEventListener('scroll', hideCellAssistance, {passive: true});
  helperClose?.addEventListener('click', hideCellAssistance);
  helper.addEventListener('focusin', (event) => window.requestAnimationFrame(() => placeAssistanceMenu(event.target)));
  helper.addEventListener('click', (event) => window.requestAnimationFrame(() => placeAssistanceMenu(event.target)));
  table.addEventListener('focusout', (event) => {
    const editedCell = event.target.closest?.('[data-catalogue-field]');
    if (editedCell) {
      const value = rowValue(editedCell.closest('tr'), editedCell.dataset.catalogueField);
      if (editedCell.dataset.catalogueField === 'Filters') renderFilterCell(editedCell, value, editedCell.dataset.originalValue || '');
      else { editedCell.replaceChildren(); renderAddedText(editedCell, value, editedCell.dataset.originalValue || ''); }
      refreshCellEditedState(editedCell);
    }
    window.requestAnimationFrame(() => {
      const focused = document.activeElement;
      const assistanceFocused = helper.contains(focused);
      if (editedCell?.dataset.catalogueField === 'CDR source' && !assistanceFocused) normaliseCatalogueRows();
      if (!focused?.closest?.('[data-catalogue-field]') && !assistanceFocused) hideCellAssistance();
    });
  });
  addFilter?.addEventListener('click', () => addFilterCondition());
  closeDialog?.addEventListener('click', () => window.parent.postMessage({type: 'dashboard-analytic:close-template-editor'}, window.location.origin));
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.key !== 'Escape' || !helper.hidden) return;
    if (hasUnsavedCatalogueChanges()) { event.preventDefault(); return; }
    event.preventDefault();
    window.parent.postMessage({type: 'dashboard-analytic:close-template-editor'}, window.location.origin);
  });
  const displayChartType = (value) => String(value || '').replace(/\b\w+/g, (word) => (
    word.toLocaleLowerCase() === 'cdf'
      ? 'CDF' : `${word.charAt(0).toLocaleUpperCase()}${word.slice(1).toLocaleLowerCase()}`
  ));
  apply.addEventListener('click', () => {
    if (!activeCell) return;
    const field = activeCell.dataset.catalogueField || '';
    const selected = Array.from(options.selectedOptions).map((option) => option.value);
    if (!selected.length || (!['Legend Position', 'Label Position', 'Label Format', 'Exclude Null/Empty', 'Exclude Zero'].includes(field) && !selected.some(Boolean))) return;
    const current = activeCell.textContent.trim();
    if (field === 'KPI') {
      const operation = kpiAggregation?.value || '';
      activeCell.textContent = operation ? `${operation}(${selected[0]})` : selected[0];
    } else if (field === 'Layout' || field === 'CDR source' || field === 'Legend Position' || field === 'Label Position' || field === 'Label Format' || field === 'Exclude Null/Empty' || field === 'Exclude Zero') {
      activeCell.textContent = selected[0];
    } else if (field === 'Chart type') {
      activeCell.textContent = displayChartType(selected[0]);
    } else if (field === 'Filters') {
      const clauses = selected.map((value) => `${value} = `).join('; ');
      renderFilterCell(activeCell, current ? `${current}; ${clauses}` : clauses);
    } else if (field === 'Legend') {
      activeCell.textContent = selected.join(', ');
    } else {
      const currentOrder = current.split(/(?:\s*×\s*|\s+[xX]\s+)/).map((value) => value.trim()).filter(Boolean);
      const retained = currentOrder.filter((value) => selected.includes(value));
      const additions = selected.filter((value) => !currentOrder.includes(value));
      activeCell.textContent = [...retained, ...additions].join(' × ');
    }
    refreshCellEditedState(activeCell);
    if (field === 'Chart type') syncConditionalVisualCells(activeCell.closest('tr'));
    if (activeCell.classList.contains('is-edited')) {
      const value = rowValue(activeCell.closest('tr'), field);
      if (field === 'Filters') renderFilterCell(activeCell, value, activeCell.dataset.originalValue || '');
      else { activeCell.replaceChildren(); renderAddedText(activeCell, value, activeCell.dataset.originalValue || ''); }
    }
    if (field === 'Filters') refreshFilterValidationAlert();
    activeCell.focus();
  });
  const saveCatalogueTemplate = async () => {
    contentField.value = serialiseCatalogueContent();
    const saveButton = saveForm.querySelector('button[type="submit"]');
    hideCellAssistance();
    if (saveButton) saveButton.disabled = true;
    showLoadingOverlay('Saving Report Template', 'Please wait while the Report Template is being saved.');
    try {
      const response = await fetch(saveForm.action, {
        method: 'POST',
        body: new FormData(saveForm),
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to save the Report Template.');
      savedCatalogueContent = contentField.value;
      // The persisted CSV is now the comparison baseline. Remove both the
      // edited-cell tint and any inline added-text marks; subsequent edits are
      // compared with these newly saved values.
      acceptCurrentCatalogueAsBaseline();
      if (window.parent !== window) window.parent.postMessage({type: 'dashboard-analytic:template-saved'}, window.location.origin);
      hideLoadingOverlay();
      showInfoDialog(`Report Template '${payload.template || 'selected template'}' has been saved.`, {
        title: 'Report Template saved',
      });
      return true;
    } catch (error) {
      hideLoadingOverlay();
    showInfoDialog(error instanceof Error ? error.message : 'Unable to save the Report Template.', {
      title: 'Report Template save failed',
        tone: 'error',
      });
      return false;
    } finally {
      hideLoadingOverlay();
      if (saveButton) saveButton.disabled = false;
    }
  };
  // Expose the editor's current state to the template picker without storing
  // unsaved table data in the browser. The CSV rendered by the server remains
  // the single source of truth after a selection change.
  editor.hasUnsavedCatalogueChanges = hasUnsavedCatalogueChanges;
  editor.saveCatalogueTemplate = saveCatalogueTemplate;
  saveForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    await saveCatalogueTemplate();
  });
  savedCatalogueContent = serialiseCatalogueContent();
});

document.querySelectorAll('[data-catalogue-auto-rename]').forEach((input) => {
  let savedValue = input.value.trim();
  const updateCatalogueIdentifier = (previousIdentifier, identifier) => {
    if (!previousIdentifier || !identifier || previousIdentifier === identifier) return;
    const row = input.closest('tr');
    const technology = input.form?.action.match(/\/admin\/report-templates\/([^/]+)\//)?.[1];
    if (!row || !technology) return;
    const previousName = decodeURIComponent(previousIdentifier);
    const oldSegment = `/admin/report-templates/${technology}/${encodeURIComponent(previousName)}/`;
    const newSegment = `/admin/report-templates/${technology}/${encodeURIComponent(identifier)}/`;
    const rawOldSegment = `/admin/report-templates/${technology}/${previousName}/`;
    const rawNewSegment = `/admin/report-templates/${technology}/${identifier}/`;
    row.querySelectorAll('form[action], a[href]').forEach((element) => {
      const attribute = element.tagName === 'A' ? 'href' : 'action';
      const value = element.getAttribute(attribute);
      if (value?.includes(rawOldSegment)) element.setAttribute(attribute, value.replace(rawOldSegment, rawNewSegment));
      else if (value?.includes(oldSegment)) element.setAttribute(attribute, value.replace(oldSegment, newSegment));
    });
    row.querySelectorAll('[data-open-template-editor]').forEach((element) => {
      const value = element.getAttribute('data-open-template-editor');
      if (value?.includes(rawOldSegment)) element.setAttribute('data-open-template-editor', value.replace(rawOldSegment, rawNewSegment));
      else if (value?.includes(oldSegment)) element.setAttribute('data-open-template-editor', value.replace(oldSegment, newSegment));
      element.setAttribute('data-template-name', input.value.trim());
    });
    document.querySelectorAll('option').forEach((option) => {
      if (option.value !== `${technology}:${previousName}`) return;
      option.value = `${technology}:${identifier}`;
      option.textContent = option.textContent.replace(previousName, identifier);
    });
    const parameters = new URLSearchParams(window.location.search);
    if (parameters.get('catalogue_technology') === technology && parameters.get('catalogue_id') === previousName) {
      parameters.set('catalogue_id', identifier);
      const query = parameters.toString();
      window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
    }
  };
  input.addEventListener('change', async () => {
    const name = input.value.trim();
    if (!name || name === savedValue || !input.form) return;
    const formData = new FormData(input.form);
    input.disabled = true;
    try {
      const response = await fetch(input.form.action, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'The template name could not be saved.');
      savedValue = String(payload.name || name).trim();
      input.value = savedValue;
      input.setAttribute('aria-label', `Name for ${savedValue}`);
      const previousIdentifier = input.form.action.match(/\/admin\/report-templates\/[^/]+\/([^/]+)\/rename$/)?.[1];
      updateCatalogueIdentifier(previousIdentifier, payload.identifier);
    } catch (error) {
      input.value = savedValue;
      showInfoDialog(error instanceof Error ? error.message : 'The template name could not be saved.', {
        title: 'Template Rename Failed',
      });
    } finally {
      input.disabled = false;
    }
  });
});

document.querySelectorAll('.catalogue-editor-picker-form').forEach((form) => {
  // The server-selected template is authoritative. Browsers can restore a
  // stale select value after navigation, making the picker claim that a
  // different template is open from the one rendered in the editor table.
  form.querySelectorAll('select[data-no-persist]').forEach((select) => {
    Array.from(select.options).forEach((option) => { option.selected = option.defaultSelected; });
  });
  const picker = form.querySelector('select[name="catalogue_selection"]');
  let selectedTemplate = picker?.value || '';
  picker?.addEventListener('change', async () => {
    const nextTemplate = picker.value;
    if (!nextTemplate || nextTemplate === selectedTemplate) return;
    const editor = document.querySelector('[data-catalogue-editor]');
    if (editor?.hasUnsavedCatalogueChanges?.()) {
      const saveChanges = await showConfirmDialog(
        'This template has unsaved changes. Save them before opening the selected template?',
        {title: 'Unsaved Report Template changes', confirmLabel: 'Save changes', cancelLabel: 'Discard changes'},
      );
      if (saveChanges) {
        const saved = await editor.saveCatalogueTemplate?.();
        if (!saved) {
          picker.value = selectedTemplate;
          return;
        }
      }
    }
    selectedTemplate = nextTemplate;
    preserveAdminScrollPosition();
    form.submit();
  });
  form.addEventListener('submit', () => preserveAdminScrollPosition());
});

const adminTemplateEditor = document.querySelector('[data-admin-template-editor]');
const adminTemplateEditorFrame = document.querySelector('[data-admin-template-editor-frame]');
const adminTemplateEditorClose = document.querySelector('[data-admin-template-editor-close]');
const adminTemplateEditorTitle = document.querySelector('[data-admin-template-editor-title]');
const closeAdminTemplateEditor = () => {
  if (adminTemplateEditor) adminTemplateEditor.hidden = true;
  if (adminTemplateEditorFrame) adminTemplateEditorFrame.removeAttribute('src');
};
document.querySelectorAll('[data-open-template-editor]').forEach((button) => {
  button.addEventListener('click', () => {
    if (!adminTemplateEditor || !adminTemplateEditorFrame) return;
    adminTemplateEditorFrame.src = button.dataset.openTemplateEditor || '';
    if (adminTemplateEditorTitle) adminTemplateEditorTitle.textContent = `Edit Report Template: "${button.dataset.templateName || 'Selected Template'}"`;
    adminTemplateEditor.hidden = false;
    adminTemplateEditorClose?.focus();
  });
});
adminTemplateEditor?.addEventListener('click', (event) => {
  if (event.target === adminTemplateEditor || event.target.closest('[data-admin-template-editor-close]')) closeAdminTemplateEditor();
});
window.addEventListener('message', (event) => {
  if (event.origin === window.location.origin && event.data?.type === 'dashboard-analytic:close-template-editor') closeAdminTemplateEditor();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && adminTemplateEditor && !adminTemplateEditor.hidden) closeAdminTemplateEditor();
});

document.querySelectorAll('form[action*="/admin/report-templates/"]').forEach((form) => {
  if (form.classList.contains('catalogue-rename-form')) return;
  form.addEventListener('submit', () => preserveAdminScrollPosition());
});

document.querySelectorAll('[data-catalogue-import-form]').forEach((form) => {
  const name = form.querySelector('[data-catalogue-import-name]');
  const file = form.querySelector('[data-catalogue-import-file]');
  const convert = form.querySelector('[data-catalogue-convert]');
  const overwrite = form.querySelector('[data-catalogue-overwrite]');
  let templateLibrary = {};
  try { templateLibrary = JSON.parse(form.dataset.catalogueTemplateLibrary || '{}'); } catch (_error) { templateLibrary = {}; }
  const currentHeaders = [
    'Slide', 'Slide Tittle', 'Slide Subtittle', 'Layout', 'Chart Tittle', 'CDR source',
    'KPI', 'Chart type', 'Filters', 'Rows Aggregation', 'Column Aggregation', 'Legend', 'Legend Position', 'Label Position', 'Label Format', 'Axis X Range', 'Axis Y Range',
  ];
  const normalizedHeader = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const hasCurrentSchema = async (selected) => {
    const headerLine = (await selected.slice(0, 65536).text())
      .replace(/^\uFEFF/, '')
      .split(/\r?\n/)
      .find((line) => line.trim());
    if (!headerLine) return false;
    const headers = headerLine.split(',').map((header) => normalizedHeader(header.replace(/^"|"$/g, '')));
    return headers.length === currentHeaders.length
      && headers.every((header, index) => header === normalizedHeader(currentHeaders[index]));
  };
  file?.addEventListener('change', () => {
    const selected = file.files?.[0];
    if (!selected || !name || name.value.trim()) return;
    name.value = selected.name.replace(/\.csv$/i, '').replace(/_+/g, ' ').trim();
  });
  form.addEventListener('submit', async (event) => {
    if (form.dataset.catalogueSubmitting === '1') return;
    event.preventDefault();
    const selected = file?.files?.[0];
    if (!selected) {
      preserveAdminScrollPosition();
      form.dataset.catalogueSubmitting = '1';
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    let shouldConvert = false;
    try {
      shouldConvert = !(await hasCurrentSchema(selected));
    } catch (_) {
      // Let the server provide the detailed error if this file cannot be read.
    }
    if (shouldConvert) {
      const accepted = await showConfirmDialog(
        'This CSV uses an older or different column layout. Compatible fields will be migrated to the current Report Templates format; new presentation fields will be left blank where they do not exist.',
        {title: 'Convert Report Templates?', confirmLabel: 'Convert and Import'},
      );
      if (!accepted) return;
    }
    const templateType = form.querySelector('[name="template_type"]')?.value?.trim().toLocaleLowerCase() || 'nsa';
    const requestedName = (name?.value?.trim() || selected.name.replace(/\.csv$/i, '').replace(/_+/g, ' ').trim());
    const existing = (templateLibrary?.[templateType] || []).find((templateName) => (
      String(templateName || '').trim().toLocaleLowerCase() === requestedName.toLocaleLowerCase()
    ));
    if (existing) {
      const accepted = await showConfirmDialog(
        `A ${templateType.toUpperCase()} template named '${existing}' already exists. Do you want to overwrite it?`,
        {title: 'Overwrite Report Template?', confirmLabel: 'Overwrite template'},
      );
      if (!accepted) return;
    }
    if (convert) convert.value = shouldConvert ? '1' : '0';
    if (overwrite) overwrite.value = existing ? '1' : '0';
    form.dataset.catalogueSubmitting = '1';
    showLoadingOverlay('Importing Report Templates', 'Validating and storing the selected template in the workspace.');
    preserveAdminScrollPosition();
    HTMLFormElement.prototype.submit.call(form);
  });
});

function datasetPreviewUrl(url, embedded = false) {
  const target = new URL(url, window.location.origin);
  if (embedded) target.searchParams.set('embedded', '1');
  else target.searchParams.delete('embedded');
  return target.toString();
}

function datasetPreviewLoadingDetails(trigger) {
  if (!trigger?.matches?.('[data-combined-dataset-preview]')) {
    return {title: 'Loading Dataset', copy: 'Please wait while the Dataset preview is loaded.'};
  }
  const labels = {data: 'Data', voice: 'Voice', speech: 'Speech'};
  const kind = labels[String(trigger.dataset.datasetKind || '').toLowerCase()] || 'selected';
  return {
    title: 'Loading Dataset',
    copy: `Checking and, when required, migrating all individual CDR-${kind} tables before loading their combined preview. This can take several minutes.`,
  };
}

function openDatasetPreviewInNewTab(url, trigger) {
  const previewWindow = window.open('', '_blank');
  if (!previewWindow) {
    showInfoDialog('The browser blocked the new Dataset preview tab. Allow pop-ups for this site and try again.', {
      title: 'Unable to open Dataset preview', tone: 'error',
    });
    return;
  }
  const loading = datasetPreviewLoadingDetails(trigger);
  previewWindow.opener = null;
  previewWindow.document.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Loading Dataset</title><style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#eef4f6;color:#17384b;font-family:Segoe UI,sans-serif}.panel{width:min(84vw,460px);box-sizing:border-box;padding:28px;border-radius:24px;background:#fff;box-shadow:0 30px 70px rgba(15,40,55,.22)}.spinner{width:42px;height:42px;border:4px solid rgba(11,122,117,.18);border-top-color:#0b7a75;border-radius:50%;animation:spin .95s linear infinite}h1{margin:16px 0 8px;font-size:24px}p{margin:0;color:#607681}.bar{height:10px;margin-top:18px;overflow:hidden;border-radius:999px;background:#e5edf0}.bar:after{content:"";display:block;width:45%;height:100%;border-radius:inherit;background:linear-gradient(90deg,#0b7a75,#53d7c8);animation:slide 1.4s ease-in-out infinite}@keyframes spin{to{transform:rotate(360deg)}}@keyframes slide{0%{transform:translateX(-120%)}50%{transform:translateX(125%)}100%{transform:translateX(250%)}}</style></head><body><main class="panel" role="status" aria-live="assertive"><div class="spinner" aria-hidden="true"></div><h1>${loading.title}</h1><p>${loading.copy}</p><div class="bar" aria-hidden="true"></div></main></body></html>`);
  previewWindow.document.close();
  previewWindow.location.replace(datasetPreviewUrl(url));
}

function openDatasetPreviewInDialog(url, trigger) {
  if (!datasetPreviewOverlay || !datasetPreviewFrame || !datasetPreviewLoading) return;
  const loading = datasetPreviewLoadingDetails(trigger);
  const title = document.getElementById('dataset-preview-loading-title');
  const copy = document.getElementById('dataset-preview-loading-copy');
  if (title instanceof HTMLElement) title.textContent = loading.title;
  if (copy instanceof HTMLElement) copy.textContent = loading.copy;
  datasetPreviewReturnFocus = trigger || document.activeElement;
  datasetPreviewLoading.hidden = false;
  datasetPreviewOverlay.hidden = false;
  document.body.classList.add('loading-active');
  datasetPreviewFrame.src = datasetPreviewUrl(url, true);
  datasetPreviewDialog?.focus();
}

async function chooseDatasetPreviewDestination(url, trigger) {
  const destination = await showConfirmDialog(
    'Choose where you want to open this Dataset preview.',
    {
      title: 'Open Dataset Preview', confirmLabel: 'New tab',
      secondaryLabel: 'Current tab', cancelLabel: 'Cancel', wideActions: true,
    },
  );
  if (destination === 'confirm') openDatasetPreviewInNewTab(url, trigger);
  if (destination === 'secondary') openDatasetPreviewInDialog(url, trigger);
}

document.addEventListener('click', (event) => {
  const previewLink = event.target.closest('[data-preview-open-link]');
  if (previewLink) {
    event.preventDefault();
    if (previewLink.matches('[data-combined-dataset-preview]')) {
      const openPreview = async () => {
        try {
          const response = await fetch(previewLink.dataset.integrityUrl || '', {credentials: 'same-origin', cache: 'no-store'});
          const integrity = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(integrity.detail || 'Unable to verify the combined dataset.');
          let url = previewLink.href;
          if (integrity.has_missing_rows) {
            const accepted = await showConfirmDialog(
              `This combined dataset contains ${integrity.row_count} of ${integrity.expected_row_count} rows from its individual CDR datasets. You can recreate it from Workspace > Datasets. Do you want to continue with the incomplete dataset?`,
              {title: 'Combined dataset has missing rows', confirmLabel: 'Open anyway', tone: 'warning'},
            );
            if (!accepted) return;
            const target = new URL(url, window.location.origin);
            target.searchParams.set('allow_incomplete', '1');
            url = target.toString();
          }
          await chooseDatasetPreviewDestination(url, previewLink);
        } catch (error) {
          showInfoDialog(error instanceof Error ? error.message : 'Unable to verify the combined dataset.', {
            title: 'Combined dataset unavailable', tone: 'error',
          });
        }
      };
      void openPreview();
      return;
    }
    void chooseDatasetPreviewDestination(previewLink.href, previewLink);
    return;
  }
  const openLink = event.target.closest('[data-datasets-analysis-open-link]');
  if (!openLink) return;
  if (openLink.target === '_blank') return;
  const datasetId = openLink.dataset.datasetId;
  if (!datasetId) return;
  event.preventDefault();
  navigateToPersistedDatasetAnalysis(
    datasetId,
    openLink.dataset.inputKind,
    openLink.dataset.loadingLabel || 'Opening datasets analysis',
  );
});

document.querySelectorAll('.collapsible-panel').forEach((panel) => {
  const chip = panel.querySelector('.collapse-chip');
  const updateChip = () => {
    if (!chip) return;
    chip.textContent = panel.open ? 'Collapse' : 'Expand';
  };
  updateChip();
  panel.addEventListener('toggle', updateChip);
});

(() => {
  const workspaceSwitchers = document.querySelectorAll('.topnav-workspace-switcher');
  if (!workspaceSwitchers.length) return;
  document.addEventListener('click', (event) => {
    workspaceSwitchers.forEach((switcher) => {
      if (switcher.open && !switcher.contains(event.target)) switcher.open = false;
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    workspaceSwitchers.forEach((switcher) => { switcher.open = false; });
  });
})();

(() => {
  if (!document.body.dataset.authenticatedUser) return;
  const activeSize = document.querySelector('[data-header-active-workspace-size]');
  const headerOptions = Array.from(document.querySelectorAll('[data-header-workspace-option]'));
  const workspaceSelectOptions = Array.from(document.querySelectorAll('[data-workspace-select] option[data-workspace-name]'));
  const workspaceTableSizes = Array.from(document.querySelectorAll('[data-workspace-size][data-workspace-id]'));
  if (!activeSize && !headerOptions.length && !workspaceTableSizes.length) return;
  let pollingStopped = false;
  let pollingInterval = null;
  const stopExpiredSessionPolling = () => {
    if (pollingStopped) return;
    pollingStopped = true;
    if (pollingInterval !== null) window.clearInterval(pollingInterval);
  };
  const refreshWorkspaceSizes = async () => {
    if (pollingStopped || document.hidden) return;
    try {
      const response = await fetch('/api/workspaces/sizes', {credentials: 'same-origin', cache: 'no-store'});
      if (response.status === 401) {
        stopExpiredSessionPolling();
        return;
      }
      if (!response.ok) return;
      const payload = await response.json();
      if (payload.authenticated === false) {
        stopExpiredSessionPolling();
        return;
      }
      const sizes = payload.sizes || {};
      if (activeSize) {
        const size = payload.active_workspace_id ? sizes[payload.active_workspace_id] : '';
        activeSize.textContent = size ? ` (${size})` : '';
      }
      headerOptions.forEach((option) => {
        const size = sizes[option.value];
        const target = option.querySelector('[data-header-workspace-size]');
        if (target && size) target.textContent = size;
      });
      workspaceSelectOptions.forEach((option) => {
        const size = sizes[option.value];
        if (size) option.textContent = `${option.dataset.workspaceName} (${size})`;
      });
      workspaceTableSizes.forEach((target) => {
        const size = sizes[target.dataset.workspaceId];
        if (size) target.textContent = size;
      });
    } catch (_error) {
      // The next lightweight refresh will retry without interrupting the page.
    }
  };
  refreshWorkspaceSizes();
  pollingInterval = window.setInterval(refreshWorkspaceSizes, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshWorkspaceSizes(); });
})();

const loadingOverlay = document.getElementById('loading-overlay');
const loadingTitle = document.getElementById('loading-title');
const loadingCopy = document.getElementById('loading-copy');
const loadingProgressBar = document.querySelector('.loading-progress-bar');
const loadingCancel = document.getElementById('loading-cancel');
const datasetPreviewOverlay = document.getElementById('dataset-preview-overlay');
const datasetPreviewDialog = datasetPreviewOverlay?.querySelector('.dataset-preview-dialog');
const datasetPreviewFrame = document.getElementById('dataset-preview-dialog-frame');
const datasetPreviewLoading = document.getElementById('dataset-preview-dialog-loading');
const datasetPreviewClose = document.getElementById('dataset-preview-dialog-close');
let datasetPreviewReturnFocus = null;
let datasetPreviewFrameWindow = null;
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmTitle = document.getElementById('confirm-title');
const confirmCopy = document.getElementById('confirm-copy');
const confirmOption = document.getElementById('confirm-option');
const confirmOptionInput = document.getElementById('confirm-option-input');
const confirmOptionLabel = document.getElementById('confirm-option-label');
const confirmAccept = document.getElementById('confirm-accept');
const confirmCancel = document.getElementById('confirm-cancel');
const confirmSecondary = document.getElementById('confirm-secondary');
const confirmTertiary = document.getElementById('confirm-tertiary');
const catalogueInsertOverlay = document.getElementById('catalogue-insert-overlay');
const catalogueInsertTitle = document.getElementById('catalogue-insert-title');
const catalogueInsertCopy = document.getElementById('catalogue-insert-copy');
const catalogueInsertChart = document.getElementById('catalogue-insert-chart');
const catalogueInsertSlide = document.getElementById('catalogue-insert-slide');
const catalogueInsertCancel = document.getElementById('catalogue-insert-cancel');
const infoOverlay = document.getElementById('info-overlay');
const infoTitle = document.getElementById('info-title');
const infoCopy = document.getElementById('info-copy');
const infoClose = document.getElementById('info-close');
const infoEyebrow = document.getElementById('info-eyebrow');
const infoIcon = document.getElementById('info-icon');
const inputKindSelect = document.querySelector('[data-input-kind-select]');
const datasetSelect = document.querySelector('[data-dataset-select]');

function closeDatasetPreviewDialog() {
  if (!datasetPreviewOverlay || datasetPreviewOverlay.hidden) return;
  datasetPreviewOverlay.hidden = true;
  document.body.classList.remove('loading-active');
  if (datasetPreviewFrame) datasetPreviewFrame.src = 'about:blank';
  datasetPreviewLoading && (datasetPreviewLoading.hidden = false);
  datasetPreviewReturnFocus?.focus?.();
  datasetPreviewReturnFocus = null;
}

function handleEmbeddedDatasetPreviewKeydown(event) {
  if (event.key !== 'Escape' || !datasetPreviewOverlay || datasetPreviewOverlay.hidden) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closeDatasetPreviewDialog();
}

datasetPreviewFrame?.addEventListener('load', () => {
  if (datasetPreviewOverlay && !datasetPreviewOverlay.hidden && datasetPreviewLoading) {
    datasetPreviewLoading.hidden = true;
  }
  try {
    datasetPreviewFrameWindow?.removeEventListener('keydown', handleEmbeddedDatasetPreviewKeydown, true);
    datasetPreviewFrameWindow = datasetPreviewFrame.contentWindow;
    datasetPreviewFrameWindow?.addEventListener('keydown', handleEmbeddedDatasetPreviewKeydown, true);
  } catch (_error) {
    // The embedded preview is same-origin; ignore a transient inaccessible document during navigation.
  }
});
datasetPreviewClose?.addEventListener('click', closeDatasetPreviewDialog);
datasetPreviewOverlay?.addEventListener('click', (event) => {
  if (event.target === datasetPreviewOverlay) closeDatasetPreviewDialog();
});
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && datasetPreviewOverlay && !datasetPreviewOverlay.hidden) {
    event.preventDefault();
    closeDatasetPreviewDialog();
  }
});
const logTypeFilter = document.querySelector('[data-log-type-filter]');
const persistencePathnames = new Set(['/datasets-analysis', '/admin']);
const datasetsAnalysisStateKey = 'dashboard-analytic:/datasets-analysis:last-query';
const datasetsAnalysisStateKeyPrefix = 'dashboard-analytic:/datasets-analysis:last-query:dataset:';
const activeDatasetStateKey = 'dashboard-analytic:active-dataset';
const adminScrollRestoreKey = 'dashboard-analytic:/admin:scroll-restore';
let hasPendingLocationRestore = false;

function preserveAdminScrollPosition() {
  if (window.location.pathname !== '/admin') return;
  try {
    window.sessionStorage.setItem(adminScrollRestoreKey, String(window.scrollY));
  } catch (_error) {
    // A blocked storage area only affects the convenience restoration.
  }
}

function restoreAdminScrollPosition() {
  if (window.location.pathname !== '/admin') return;
  try {
    const value = window.sessionStorage.getItem(adminScrollRestoreKey);
    if (value === null) return;
    window.sessionStorage.removeItem(adminScrollRestoreKey);
    const top = Number(value);
    if (Number.isFinite(top) && top > 0) {
      requestAnimationFrame(() => window.scrollTo({top, behavior: 'auto'}));
    }
  } catch (_error) {
    // A blocked storage area only affects the convenience restoration.
  }
}

restoreAdminScrollPosition();

function hasMeaningfulDatasetsAnalysisState(params) {
  if (!params) return false;
  for (const [key, value] of params.entries()) {
    if (key === 'dataset_id' || key === 'input_kind' || key === 'load') continue;
    if ((key === 'aggregation' || key === 'cdf_grouping') && String(value || '').trim().toLowerCase() === 'all') continue;
    if (String(value || '').trim()) {
      return true;
    }
  }
  return false;
}

function sanitizeDatasetsAnalysisState(params) {
  const source = params instanceof URLSearchParams ? params : new URLSearchParams(params || '');
  const sanitized = new URLSearchParams(source.toString());
  sanitized.delete('aggregation_overrides');
  sanitized.delete('cdf_overrides');
  return sanitized;
}

function buildDatasetsAnalysisStateKey(datasetId) {
  const normalizedDatasetId = String(datasetId || '').trim();
  return normalizedDatasetId ? `${datasetsAnalysisStateKeyPrefix}${normalizedDatasetId}` : datasetsAnalysisStateKey;
}

function getDatasetsAnalysisStateKeyForParams(params) {
  return buildDatasetsAnalysisStateKey(params?.get?.('dataset_id'));
}

function getPersistedDatasetsAnalysisQuery(params) {
  const stateKey = getDatasetsAnalysisStateKeyForParams(params || new URLSearchParams());
  let persistedQuery = window.localStorage.getItem(stateKey);
  if (!persistedQuery && stateKey !== datasetsAnalysisStateKey) {
    persistedQuery = window.localStorage.getItem(datasetsAnalysisStateKey);
  }
  return persistedQuery;
}

function persistDatasetsAnalysisState(params) {
  if (!hasMeaningfulDatasetsAnalysisState(params)) return;
  try {
    const sanitized = sanitizeDatasetsAnalysisState(params);
    const serialized = sanitized.toString();
    window.localStorage.setItem(getDatasetsAnalysisStateKeyForParams(params), serialized);
    window.localStorage.setItem(datasetsAnalysisStateKey, serialized);
  } catch (_error) {
    // Ignore storage failures.
  }
}

function persistActiveDatasetState(params) {
  const datasetId = String(params.get('dataset_id') || '').trim();
  if (!datasetId) return;
  const inputKind = String(params.get('input_kind') || '').trim();
  try {
    window.localStorage.setItem(activeDatasetStateKey, JSON.stringify({
      dataset_id: datasetId,
      input_kind: inputKind,
    }));
  } catch (_error) {
    // Ignore storage failures.
  }
}

function buildRestoredDatasetsAnalysisUrl(currentParams, persistedDatasetsAnalysisQuery) {
  const persistedParams = sanitizeDatasetsAnalysisState(new URLSearchParams(persistedDatasetsAnalysisQuery || ''));
  const merged = new URLSearchParams(persistedParams.toString());
  const currentDatasetId = String(currentParams.get('dataset_id') || '').trim();
  const currentInputKind = String(currentParams.get('input_kind') || '').trim();
  if (currentDatasetId) {
    merged.set('dataset_id', currentDatasetId);
  }
  if (currentInputKind) {
    merged.set('input_kind', currentInputKind);
  } else {
    merged.delete('input_kind');
  }
  const query = merged.toString();
  return query ? `/datasets-analysis?${query}` : '/datasets-analysis';
}

function buildDatasetAnalysisUrl(params) {
  const persistedDatasetsAnalysisQuery = getPersistedDatasetsAnalysisQuery(params);
  if (persistedDatasetsAnalysisQuery) {
    return buildRestoredDatasetsAnalysisUrl(params, persistedDatasetsAnalysisQuery);
  }
  const query = params.toString();
  return query ? `/datasets-analysis?${query}` : '/datasets-analysis';
}

function navigateToPersistedDatasetAnalysis(datasetId, inputKind, loadingLabel = 'Opening datasets analysis') {
  const params = new URLSearchParams();
  const normalizedDatasetId = String(datasetId || '').trim();
  const normalizedInputKind = String(inputKind || '').trim();
  if (!normalizedDatasetId) return false;
  params.set('dataset_id', normalizedDatasetId);
  if (normalizedInputKind) {
    params.set('input_kind', normalizedInputKind);
  }
  showLoadingOverlay(loadingLabel);
  replaceLocation(buildDatasetAnalysisUrl(params));
  return true;
}

function restoreActiveDatasetState() {
  try {
    const rawValue = window.localStorage.getItem(activeDatasetStateKey);
    if (!rawValue) return null;
    const parsed = JSON.parse(rawValue);
    if (!parsed || !parsed.dataset_id) return null;
    return {
      dataset_id: String(parsed.dataset_id),
      input_kind: String(parsed.input_kind || ''),
    };
  } catch (_error) {
    return null;
  }
}

function replaceLocation(url) {
  hasPendingLocationRestore = true;
  window.location.replace(url);
}

function buildDatasetsAnalysisParamsFromForm(form) {
  const params = new URLSearchParams();
  const formData = new FormData(form);
  for (const [key, value] of formData.entries()) {
    if (value == null) continue;
    const normalized = String(value);
    if (!normalized.trim()) continue;
    params.append(key, normalized);
  }
  form.querySelectorAll('select[multiple][name]').forEach((select) => {
    const enabledOptions = Array.from(select.options).filter((option) => !option.disabled);
    const selectedCount = enabledOptions.filter((option) => option.selected).length;
    if (enabledOptions.length > 0 && selectedCount === 0) {
      params.append('__empty_filter', select.name);
    }
  });
  document.querySelectorAll(`[form="${form.id}"][name]`).forEach((control) => {
    if (form.contains(control)) return;
    const tagName = String(control.tagName || '').toLowerCase();
    if (tagName !== 'select' && tagName !== 'input' && tagName !== 'textarea') return;
    if (control.disabled) return;
    if (tagName === 'select' && control.multiple) {
      params.delete(control.name);
      const enabledOptions = Array.from(control.options).filter((option) => !option.disabled);
      const selectedOptions = enabledOptions.filter((option) => option.selected);
      selectedOptions.forEach((option) => params.append(control.name, String(option.value)));
      if (enabledOptions.length > 0 && selectedOptions.length === 0) {
        params.append('__empty_filter', control.name);
      }
      return;
    }
    if ((tagName === 'input') && String(control.type || '').toLowerCase() === 'checkbox') {
      params.delete(control.name);
      if (control.checked) params.append(control.name, String(control.value || 'on'));
      return;
    }
    params.delete(control.name);
    const value = String(control.value || '').trim();
    if (value) {
      params.append(control.name, value);
    }
  });
  return params;
}

function syncDatasetsAnalysisHiddenControl(name, value) {
  const form = document.getElementById('datasets-analysis-filters-form');
  if (!form) return;
  const control = form.querySelector(`input[type="hidden"][name="${name}"]`);
  if (control) {
    control.value = String(value || 'all').trim() || 'all';
  }
}

function parseAggregationOverrides(rawValue) {
  const overrides = new Map();
  String(rawValue || '')
    .split(';')
    .map((entry) => entry.trim())
    .filter(Boolean)
    .forEach((entry) => {
      const separator = entry.indexOf('=');
      if (separator <= 0) return;
      const metric = entry.slice(0, separator).trim();
      const aggregation = entry.slice(separator + 1).trim();
      if (metric && aggregation) {
        overrides.set(metric, aggregation);
      }
    });
  return overrides;
}

function formatAggregationOverrides(overrides) {
  return Array.from(overrides.entries())
    .filter(([metric, aggregation]) => metric && aggregation)
    .map(([metric, aggregation]) => `${metric}=${aggregation}`)
    .join(';');
}

function canPersistControl(control) {
  if (!control || !persistencePathnames.has(window.location.pathname)) return false;
  if (control.hasAttribute('data-no-persist')) return false;
  if (!control.name || control.disabled) return false;
  const tagName = String(control.tagName || '').toLowerCase();
  const type = String(control.type || '').toLowerCase();
  if (tagName === 'input' && ['hidden', 'file', 'submit', 'button', 'image', 'reset'].includes(type)) return false;
  return ['input', 'select', 'textarea'].includes(tagName);
}

function buildPersistenceKey(control) {
  const explicitForm = control.getAttribute('form');
  const ownerForm = control.form;
  const formKey = explicitForm || ownerForm?.id || ownerForm?.getAttribute('action') || 'standalone';
  return `dashboard-analytic:${window.location.pathname}:${formKey}:${control.name}`;
}

function serializeControlValue(control) {
  if (control.tagName === 'SELECT' && control.multiple) {
    return JSON.stringify(Array.from(control.selectedOptions).map((option) => option.value));
  }
  if (String(control.type || '').toLowerCase() === 'checkbox') {
    return JSON.stringify(Boolean(control.checked));
  }
  if (String(control.type || '').toLowerCase() === 'radio') {
    return JSON.stringify(control.checked ? control.value : null);
  }
  return JSON.stringify(control.value);
}

function restoreControlValue(control, rawValue) {
  let parsedValue;
  try {
    parsedValue = JSON.parse(rawValue);
  } catch (_error) {
    return;
  }

  if (control.tagName === 'SELECT' && control.multiple) {
    const selectedValues = new Set(Array.isArray(parsedValue) ? parsedValue.map(String) : []);
    Array.from(control.options).forEach((option) => {
      option.selected = selectedValues.has(String(option.value));
    });
    return;
  }
  if (String(control.type || '').toLowerCase() === 'checkbox') {
    control.checked = Boolean(parsedValue);
    return;
  }
  if (String(control.type || '').toLowerCase() === 'radio') {
    control.checked = parsedValue !== null && String(control.value) === String(parsedValue);
    return;
  }
  control.value = parsedValue == null ? '' : String(parsedValue);
}

function queryAlreadyControlsValue(control) {
  if (window.location.pathname !== '/datasets-analysis') return false;
  const params = new URLSearchParams(window.location.search);
  if (
    control &&
    (control.name === 'aggregation' || control.name === 'cdf_grouping') &&
    String(params.get(control.name) || '').trim().toLowerCase() === 'all'
  ) {
    return false;
  }
  return params.has(control.name);
}

function getPersistedControlValue(control) {
  if (!canPersistControl(control)) return null;
  const rawValue = window.localStorage.getItem(buildPersistenceKey(control));
  if (rawValue == null) return null;
  try {
    const parsed = JSON.parse(rawValue);
    return parsed == null ? null : String(parsed);
  } catch (_error) {
    return null;
  }
}

function setupPersistentControls() {
  document.querySelectorAll('input[name], select[name], textarea[name]').forEach((control) => {
    if (!canPersistControl(control)) return;
    const key = buildPersistenceKey(control);
    const storedValue = window.localStorage.getItem(key);
    if (storedValue !== null && !queryAlreadyControlsValue(control)) {
      restoreControlValue(control, storedValue);
    }

    const persist = () => {
      try {
        window.localStorage.setItem(key, serializeControlValue(control));
      } catch (_error) {
        // Ignore storage quota / privacy mode failures.
      }
    };

    control.addEventListener('change', persist);
    control.addEventListener('input', persist);
  });
}

function setupPersistentPanelState() {
  document.querySelectorAll('details[data-panel-state-key]').forEach((panel) => {
    const sessionScoped = panel.dataset.panelStateStorage === 'session';
    const sessionMarker = document.body.dataset.authenticatedSession || 'anonymous';
    const stateKey = `dashboard-analytic:panel:${panel.dataset.panelStateKey}${sessionScoped ? `:${sessionMarker}` : ''}`;
    const storage = sessionScoped ? window.sessionStorage : window.localStorage;
    const storedValue = storage.getItem(stateKey);
    if (storedValue !== null) {
      panel.open = storedValue === 'open';
    }

    panel.addEventListener('toggle', () => {
      try {
        storage.setItem(stateKey, panel.open ? 'open' : 'closed');
      } catch (_error) {
        // Ignore storage failures.
      }
    });
  });
}

function setupSearchableSingleSelects() {
  document.querySelectorAll('select[data-searchable-select]:not([multiple])').forEach((select) => {
    if (select.dataset.searchableReady === '1') return;
    select.dataset.searchableReady = '1';
    select.classList.add('searchable-select-native');

    const shell = document.createElement('div');
    shell.className = 'searchable-select-shell';
    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'searchable-select-input';
    input.placeholder = 'Search values…';
    input.setAttribute('aria-label', select.getAttribute('aria-label') || 'Search values');
    input.disabled = select.disabled;
    const menu = document.createElement('div');
    menu.className = 'searchable-select-menu';
    menu.hidden = true;

    const syncInput = () => {
      const current = Array.from(select.options).find((option) => option.selected);
      input.value = current?.textContent?.trim() || '';
    };
    const renderOptions = (query = '') => {
      const normalized = query.trim().toLocaleLowerCase();
      menu.replaceChildren();
      const visibleOptions = Array.from(select.options).filter((option) => (
        !option.disabled && (!normalized || (option.textContent || '').toLocaleLowerCase().includes(normalized))
      ));
      if (select.closest('[data-catalogue-editor]')) {
        visibleOptions.sort((left, right) => Number(right.selected) - Number(left.selected)
          || String(left.textContent || '').localeCompare(String(right.textContent || '')));
      }
      visibleOptions.forEach((option) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'searchable-select-option';
        item.textContent = option.textContent || option.value;
        item.setAttribute('aria-selected', String(option.selected));
        item.addEventListener('click', () => {
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          select.dispatchEvent(new Event('input', { bubbles: true }));
          syncInput();
          menu.hidden = true;
        });
        menu.appendChild(item);
      });
      if (!menu.childElementCount) {
        const empty = document.createElement('p');
        empty.className = 'searchable-select-empty';
        empty.textContent = 'No matching values';
        menu.appendChild(empty);
      }
    };
    const filterSingleSelect = () => {
      renderOptions(input.value);
      menu.hidden = false;
    };
    input.addEventListener('focus', () => {
      // Replace the current selection when the user starts typing a search.
      input.select();
      renderOptions('');
      menu.hidden = false;
    });
    input.addEventListener('input', filterSingleSelect);
    input.addEventListener('keyup', filterSingleSelect);
    input.addEventListener('search', filterSingleSelect);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { menu.hidden = true; input.blur(); }
    });
    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) menu.hidden = true;
    });
    select.addEventListener('change', syncInput);
    const rebuildOnOptionUpdate = () => {
      select.removeEventListener('searchable-select:options-updated', rebuildOnOptionUpdate);
      shell.remove();
      select.classList.remove('searchable-select-native');
      delete select.dataset.searchableReady;
    };
    select.addEventListener('searchable-select:options-updated', rebuildOnOptionUpdate);
    select.after(shell);
    shell.append(input, menu);
    syncInput();
  });
}

function setupWorkspaceUserPickers() {
  document.querySelectorAll('[data-workspace-user-picker]').forEach((picker) => {
    if (picker.dataset.workspaceUserPickerReady === '1') return;
    picker.dataset.workspaceUserPickerReady = '1';
    const search = picker.querySelector('.workspace-user-picker-search');
    const toggle = picker.querySelector('.workspace-user-picker-toggle');
    const menu = picker.querySelector('.workspace-user-picker-menu');
    const options = Array.from(picker.querySelectorAll('.workspace-user-picker-menu label'));
    const checkboxes = options.map((option) => option.querySelector('input[type="checkbox"]')).filter((checkbox) => checkbox && !checkbox.disabled);
    const portalize = Boolean(picker.closest('.table-wrap')) && Boolean(menu);
    const menuHome = menu?.parentNode;
    const menuNextSibling = menu?.nextSibling;

    const positionPortalMenu = () => {
      if (!portalize || !menu || !picker.open) return;
      const bounds = picker.getBoundingClientRect();
      const availableHeight = Math.max(8 * 16, window.innerHeight - bounds.bottom - 16);
      Object.assign(menu.style, {
        left: `${Math.max(8, bounds.left)}px`,
        top: `${bounds.bottom - 1}px`,
        width: `${Math.max(bounds.width, 184)}px`,
        maxHeight: `${Math.min(224, availableHeight)}px`,
      });
    };
    const restorePortalMenu = () => {
      if (!portalize || !menu || !menuHome || !menu.classList.contains('workspace-user-picker-menu-portal')) return;
      menuHome.insertBefore(menu, menuNextSibling);
      menu.classList.remove('workspace-user-picker-menu-portal');
      menu.removeAttribute('style');
    };

    const filter = () => {
      const query = (search?.value || '').trim().toLocaleLowerCase();
      options.forEach((option) => {
        option.hidden = Boolean(query) && !option.textContent.toLocaleLowerCase().includes(query);
      });
    };
    search?.addEventListener('input', filter);
    search?.addEventListener('keyup', filter);
    search?.addEventListener('search', filter);
    toggle?.addEventListener('click', () => {
      const shouldSelectAll = checkboxes.some((checkbox) => !checkbox.checked);
      checkboxes.forEach((checkbox) => { checkbox.checked = shouldSelectAll; });
      filter();
    });
    picker.addEventListener('toggle', () => {
      const parentPanel = picker.closest('.collapsible-panel');
      if (parentPanel) {
        parentPanel.classList.toggle(
          'workspace-user-picker-open',
          Boolean(parentPanel.querySelector('.workspace-user-picker[open]')),
        );
      }
      if (picker.open && search) {
        if (portalize && menu) {
          menu.classList.add('workspace-user-picker-menu-portal');
          document.body.append(menu);
          positionPortalMenu();
        }
        search.value = '';
        filter();
        window.setTimeout(() => search.focus(), 0);
      } else {
        restorePortalMenu();
      }
    });
    document.addEventListener('click', (event) => {
      const clickInPortalMenu = Boolean(menu?.classList.contains('workspace-user-picker-menu-portal') && menu.contains(event.target));
      if (picker.open && !picker.contains(event.target) && !clickInPortalMenu) {
        picker.open = false;
      }
    });
    window.addEventListener('resize', positionPortalMenu);
    document.addEventListener('scroll', positionPortalMenu, true);
  });
}

const workspaceElementExportTargets = new Set([
  'slides-templates', 'auto-calculated-fields', 'dashboards', 'operator-mappings', 'vendor-mappings',
]);

function normalizeExportTargetSelection(select) {
  if (!select.matches('[data-export-target-select]')) return;
  const options = Array.from(select.options);
  options.forEach((option) => {
    if (option.dataset.exportOriginallyDisabled === undefined) {
      option.dataset.exportOriginallyDisabled = String(option.disabled);
    }
    option.disabled = option.dataset.exportOriginallyDisabled === 'true';
  });
  const selected = options.filter((option) => option.selected && !option.disabled);
  const fullEnvironment = selected.find((option) => option.value === 'full-environment');
  if (fullEnvironment) {
    options.forEach((option) => {
      if (option !== fullEnvironment) {
        option.selected = false;
        option.disabled = true;
      }
    });
    return;
  }
  const hasFullWorkspace = selected.some((option) => option.value.startsWith('workspace:'));
  options.forEach((option) => {
    if (hasFullWorkspace && workspaceElementExportTargets.has(option.value)) {
      option.selected = false;
      option.disabled = true;
    }
  });
}

function setupCustomMultiSelects() {
  document.querySelectorAll('select[multiple]').forEach((select) => {
    if (select.dataset.multiselectReady === '1') return;
    select.dataset.multiselectReady = '1';
    select.classList.add('multiselect-native');
    normalizeExportTargetSelection(select);

    const shell = document.createElement('div');
    shell.className = 'multiselect-shell';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'multiselect-trigger';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.disabled = select.disabled;
    if (select.disabled) trigger.setAttribute('aria-disabled', 'true');

    const triggerLabel = document.createElement('span');
    triggerLabel.className = 'multiselect-trigger-label';

    const triggerChip = document.createElement('span');
    triggerChip.className = 'multiselect-trigger-chip';

    trigger.appendChild(triggerLabel);
    trigger.appendChild(triggerChip);

    const menu = document.createElement('div');
    menu.className = 'multiselect-menu';
    menu.hidden = true;
    const singleChoice = select.dataset.multiselectSingle === 'true';
    const singleChoiceName = singleChoice ? `multiselect-single-${select.id || Math.random().toString(36).slice(2)}` : '';
    const autoCloseDelay = Number.parseInt(select.dataset.multiselectAutoClose || '', 10);
    let autoCloseTimer = null;
    const cancelAutoClose = () => {
      if (autoCloseTimer !== null) {
        window.clearTimeout(autoCloseTimer);
        autoCloseTimer = null;
      }
    };
    const scheduleAutoClose = () => {
      if (!Number.isFinite(autoCloseDelay) || autoCloseDelay <= 0 || menu.hidden) return;
      cancelAutoClose();
      autoCloseTimer = window.setTimeout(() => {
        menu.hidden = true;
        syncTrigger();
        autoCloseTimer = null;
      }, autoCloseDelay);
    };

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'multiselect-search';
    search.placeholder = 'Filter values…';
    search.setAttribute('aria-label', 'Filter available values');
    menu.appendChild(search);

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.className = 'multiselect-action';
    if (select.closest('.reporting-stack')) {
      // Reporting has its own button palette.  Mark this generated control so
      // it cannot inherit the strong primary-reporting button treatment.
      actionButton.classList.add('reporting-multiselect-action');
    }
    actionButton.textContent = 'Select All / None';
    if (!singleChoice) menu.appendChild(actionButton);

    const syncTrigger = () => {
      const enabledOptions = Array.from(select.options).filter((option) => !option.disabled);
      const selectedOptions = enabledOptions.filter((option) => option.selected).map((option) => option.textContent?.trim()).filter(Boolean);
      const totalEnabled = enabledOptions.length;
      if (totalEnabled === 0) {
        triggerLabel.textContent = 'No values';
      } else if (selectedOptions.length === 0) {
        triggerLabel.textContent = 'None Selected';
      } else if (selectedOptions.length === 1) {
        // A one-item Reporting source selector is already fully selected, but
        // its file name is more useful than the generic "All values" summary.
        triggerLabel.textContent = selectedOptions[0];
      } else if (totalEnabled > 0 && selectedOptions.length === totalEnabled) {
        triggerLabel.textContent = 'All values';
      } else {
        triggerLabel.textContent = `${selectedOptions.length}/${totalEnabled} selected`;
      }
      trigger.setAttribute('aria-expanded', String(!menu.hidden));
    };

    const dispatchNativeChange = () => {
      select.dispatchEvent(new Event('change', {bubbles: true}));
      select.dispatchEvent(new Event('input', {bubbles: true}));
      syncTrigger();
    };

    const selectAllOrNone = () => {
      cancelAutoClose();
      const options = Array.from(select.options).filter((option) => !option.disabled);
      const shouldSelectAll = options.some((option) => !option.selected);
      options.forEach((option) => {
        option.selected = shouldSelectAll;
      });
      normalizeExportTargetSelection(select);
      Array.from(menu.querySelectorAll('input[type="checkbox"][data-option-value]')).forEach((checkbox) => {
        if (!checkbox.disabled) {
          checkbox.checked = shouldSelectAll;
        }
      });
      dispatchNativeChange();
    };

    if (!singleChoice) actionButton.addEventListener('click', selectAllOrNone);

    const groupedOptions = select.dataset.multiselectGroups === 'true';
    let previousGroup = '';
    Array.from(select.options).forEach((option) => {
      const group = groupedOptions && option.parentElement instanceof HTMLOptGroupElement
        ? String(option.parentElement.label || '').trim() : '';
      if (group && group !== previousGroup) {
        const heading = document.createElement('div');
        heading.className = 'multiselect-group-label';
        heading.dataset.multiselectGroup = group;
        heading.textContent = group;
        menu.appendChild(heading);
        previousGroup = group;
      }
      const optionLabel = document.createElement('label');
      optionLabel.className = 'multiselect-option';
      if (group) optionLabel.dataset.multiselectGroup = group;

      const checkbox = document.createElement('input');
      checkbox.type = singleChoice ? 'radio' : 'checkbox';
      if (singleChoice) checkbox.name = singleChoiceName;
      checkbox.checked = option.selected;
      checkbox.setAttribute('data-option-value', option.value);
      checkbox.disabled = option.disabled;

      const text = document.createElement('span');
      text.textContent = option.textContent || option.value;

      checkbox.addEventListener('change', () => {
        if (option.disabled) return;
        if (singleChoice) {
          Array.from(select.options).forEach((item) => { item.selected = false; });
          option.selected = true;
        } else {
          option.selected = checkbox.checked;
        }
        normalizeExportTargetSelection(select);
        dispatchNativeChange();
        if (singleChoice) menu.hidden = true;
      });

      if (option.disabled) {
        optionLabel.classList.add('is-disabled');
        optionLabel.title = 'This metric is not selectable because the dataset has no numeric values for it.';
      }

      optionLabel.appendChild(checkbox);
      optionLabel.appendChild(text);
      menu.appendChild(optionLabel);
    });

    const orderSelectedOptionsFirst = () => {
      if (!select.closest('[data-catalogue-editor]')) return;
      const optionLabels = Array.from(menu.querySelectorAll('.multiselect-option'));
      optionLabels.sort((left, right) => {
        const leftSelected = Boolean(left.querySelector('input[type="checkbox"]')?.checked);
        const rightSelected = Boolean(right.querySelector('input[type="checkbox"]')?.checked);
        return Number(rightSelected) - Number(leftSelected)
          || String(left.textContent || '').localeCompare(String(right.textContent || ''));
      });
      menu.append(...optionLabels);
    };

    const filterMultiSelect = () => {
      const query = search.value.trim().toLocaleLowerCase();
      Array.from(menu.querySelectorAll('.multiselect-option')).forEach((optionLabel) => {
        const text = optionLabel.textContent?.toLocaleLowerCase() || '';
        optionLabel.hidden = Boolean(query) && !text.includes(query);
      });
      if (groupedOptions) {
        Array.from(menu.querySelectorAll('.multiselect-group-label')).forEach((heading) => {
          const group = heading.dataset.multiselectGroup;
          heading.hidden = Array.from(menu.querySelectorAll(`.multiselect-option[data-multiselect-group="${CSS.escape(group || '')}"]`))
            .every((optionLabel) => optionLabel.hidden);
        });
      }
    };
    search.addEventListener('input', filterMultiSelect);
    search.addEventListener('keyup', filterMultiSelect);
    search.addEventListener('search', filterMultiSelect);

    const syncCheckboxes = () => {
      Array.from(menu.querySelectorAll('input[data-option-value]')).forEach((checkbox) => {
        const option = Array.from(select.options).find((item) => item.value === checkbox.getAttribute('data-option-value'));
        if (option) {
          checkbox.checked = option.selected;
          checkbox.disabled = option.disabled;
          const optionLabel = checkbox.closest('.multiselect-option');
          optionLabel?.classList.toggle('is-disabled', option.disabled);
          if (optionLabel) optionLabel.title = option.disabled
            ? 'This option is already included by the selected package.' : '';
        }
      });
      orderSelectedOptionsFirst();
      syncTrigger();
    };

    trigger.addEventListener('click', () => {
      cancelAutoClose();
      menu.hidden = !menu.hidden;
      syncTrigger();
      if (!menu.hidden) search.focus();
    });

    if (Number.isFinite(autoCloseDelay) && autoCloseDelay > 0) {
      shell.addEventListener('pointerenter', cancelAutoClose);
      shell.addEventListener('pointerleave', scheduleAutoClose);
    }

    document.addEventListener('click', (event) => {
      if (!shell.contains(event.target)) {
        cancelAutoClose();
        menu.hidden = true;
        syncTrigger();
      }
    });

    select.addEventListener('change', syncCheckboxes);
    const rebuildOnOptionUpdate = () => {
      // Dynamic option lists need a new checkbox menu to remain in sync.
      select.removeEventListener('multiselect:options-updated', rebuildOnOptionUpdate);
      shell.remove();
      select.classList.remove('multiselect-native');
      delete select.dataset.multiselectReady;
      setupCustomMultiSelects();
    };
    select.addEventListener('multiselect:options-updated', rebuildOnOptionUpdate);
    select.after(shell);
    shell.appendChild(trigger);
    shell.appendChild(menu);
    syncCheckboxes();
  });
}

function setupPagePanelNavigator() {
  const navigator = document.querySelector('[data-page-panel-navigator]');
  const main = document.querySelector('main');
  if (!navigator || !main || navigator.dataset.ready === '1') return;
  navigator.dataset.ready = '1';
  const toggle = navigator.querySelector('[data-page-panel-navigator-toggle]');
  const close = navigator.querySelector('[data-page-panel-navigator-close]');
  const list = navigator.querySelector('[data-page-panel-navigator-list]');
  const empty = navigator.querySelector('[data-page-panel-navigator-empty]');
  let panels = [];
  let rebuildTimer = 0;
  let sectionObserver = null;
  let generatedPanelId = 0;

  const activeTab = document.querySelector('.module-tab.active');
  const themeClasses = {
    'module-tab-workspace': 'workspace',
    'module-tab-datasets-analysis': 'datasets',
    'module-tab-e2e-dashboards': 'dashboards',
    'module-tab-reporting': 'reporting',
    'module-tab-chart-builder': 'builder',
    'module-tab-utility': 'utility',
    'module-tab-app-logs': 'logs',
    'module-tab-config': 'config',
    'module-tab-admin': 'admin',
  };
  navigator.dataset.theme = Object.entries(themeClasses).find(([className]) => activeTab?.classList.contains(className))?.[1]
    || (window.location.pathname.startsWith('/datasets/') ? 'datasets' : 'utility');

  const setOpen = (open) => {
    navigator.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
  };
  const panelIsVisible = (panel) => {
    if (panel.hidden || panel.closest('[hidden]')) return false;
    const style = window.getComputedStyle(panel);
    return style.display !== 'none' && style.visibility !== 'hidden' && panel.getClientRects().length > 0;
  };
  const panelLabel = (panel, index) => {
    const summary = panel.matches('details') ? panel.querySelector(':scope > summary') : null;
    const heading = summary?.querySelector('h1,h2,h3,h4') || panel.querySelector('h1,h2,h3,h4');
    const eyebrow = summary?.querySelector('.eyebrow') || panel.querySelector('.eyebrow');
    const explicitLabel = panel.dataset.pagePanelLabel;
    const label = explicitLabel || (index === 0 ? eyebrow?.textContent || heading?.textContent : heading?.textContent || eyebrow?.textContent);
    return String(label || `Panel ${index + 1}`).trim();
  };
  const visibleMainPanels = () => {
    const topLevelPanels = Array.from(main.querySelectorAll('article.panel, details.panel, section.panel')).filter((panel) => {
      const parentPanel = panel.parentElement?.closest('article.panel, details.panel, section.panel');
      return !parentPanel;
    });
    const visiblePanels = topLevelPanels.filter((panel) => (
      panelIsVisible(panel)
      && panel.dataset.pagePanelNavigation !== 'exclude'
      && !panel.closest('.confirm-overlay, .dataset-preview-overlay, [role="dialog"]')
    ));
    if (navigator.dataset.theme !== 'admin') return visiblePanels;
    // Admin deliberately uses CSS `order` to bring package controls directly
    // below its overview. Mirror that rendered order in Sections.
    return visiblePanels
      .map((panel, index) => ({
        panel,
        index,
        order: Number.parseInt(window.getComputedStyle(panel).order, 10) || 0,
      }))
      .sort((left, right) => left.order - right.order || left.index - right.index)
      .map(({panel}) => panel);
  };
  const markActive = (panel) => {
    list.querySelectorAll('[data-page-panel-target]').forEach((button) => {
      const active = button.dataset.pagePanelTarget === panel?.id;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current', 'location');
      else button.removeAttribute('aria-current');
    });
  };
  const rebuild = () => {
    panels = visibleMainPanels();
    list.replaceChildren();
    sectionObserver?.disconnect();
    const mainMenu = document.createElement('button');
    mainMenu.type = 'button';
    mainMenu.className = 'page-panel-main-menu';
    mainMenu.dataset.pagePanelTarget = 'main-menu';
    const mainMenuLabel = document.createElement('span');
    mainMenuLabel.textContent = 'Main Menu';
    const mainMenuIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    mainMenuIcon.setAttribute('viewBox', '0 0 24 24');
    mainMenuIcon.setAttribute('aria-hidden', 'true');
    const mainMenuPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    mainMenuPath.setAttribute('d', 'M3 11.5 12 4l9 7.5M5.5 10v10h13V10M9.5 20v-6h5v6');
    mainMenuIcon.append(mainMenuPath);
    mainMenu.append(mainMenuLabel, mainMenuIcon);
    mainMenu.addEventListener('click', () => {
      window.scrollTo({top: 0, left: 0, behavior: 'smooth'});
      markActive({id: 'main-menu'});
      setOpen(false);
    });
    list.append(mainMenu);
    panels.forEach((panel, index) => {
      while (!panel.id) {
        generatedPanelId += 1;
        const candidate = `page-panel-${generatedPanelId}`;
        if (!document.getElementById(candidate)) panel.id = candidate;
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.pagePanelTarget = panel.id;
      button.textContent = panelLabel(panel, index);
      button.addEventListener('click', () => {
        panel.scrollIntoView({behavior: 'smooth', block: 'start'});
        markActive(panel);
        setOpen(false);
      });
      list.append(button);
    });
    empty.hidden = true;
    sectionObserver = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
      if (visible[0]) markActive(visible[0].target);
    }, {rootMargin: '-12% 0px -70% 0px', threshold: 0});
    panels.forEach((panel) => sectionObserver.observe(panel));
  };
  const scheduleRebuild = () => {
    window.clearTimeout(rebuildTimer);
    rebuildTimer = window.setTimeout(rebuild, 60);
  };

  toggle.addEventListener('click', () => {
    const opening = !navigator.classList.contains('is-open');
    if (opening) rebuild();
    setOpen(opening);
  });
  close.addEventListener('click', () => setOpen(false));
  document.addEventListener('pointerdown', (event) => {
    if (navigator.classList.contains('is-open') && !navigator.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && navigator.classList.contains('is-open')) {
      setOpen(false);
      toggle.focus();
    }
  });
  document.addEventListener('page-panel-navigation:update', scheduleRebuild);
  window.addEventListener('resize', scheduleRebuild, {passive: true});
  new MutationObserver(scheduleRebuild).observe(main, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['hidden', 'class', 'style'],
  });
  rebuild();
}

function setupModuleNavigator() {
  const navigator = document.querySelector('[data-module-navigator]');
  if (!navigator || navigator.dataset.ready === '1') return;
  navigator.dataset.ready = '1';
  const toggle = navigator.querySelector('[data-module-navigator-toggle]');
  const close = navigator.querySelector('[data-module-navigator-close]');
  if (!(toggle instanceof HTMLButtonElement) || !(close instanceof HTMLButtonElement)) return;

  const sectionsNavigator = document.querySelector('[data-page-panel-navigator]');
  navigator.dataset.theme = sectionsNavigator?.dataset.theme || 'utility';
  const setOpen = (open) => {
    navigator.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
  };
  toggle.addEventListener('click', () => setOpen(!navigator.classList.contains('is-open')));
  close.addEventListener('click', () => setOpen(false));
  navigator.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setOpen(false)));
  document.addEventListener('pointerdown', (event) => {
    if (navigator.classList.contains('is-open') && !navigator.contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !navigator.classList.contains('is-open')) return;
    setOpen(false);
    toggle.focus();
  });
}

function setupEdgeNavigatorReveal() {
  if (document.body.dataset.edgeNavigatorsReady === '1') return;
  const navigators = Array.from(document.querySelectorAll(
    '.page-panel-navigator, .help-navigator, .release-navigator',
  ));
  if (!navigators.length) return;
  document.body.dataset.edgeNavigatorsReady = '1';
  const autoHideDelay = 5000;
  const concealTimers = {left: 0, right: 0};
  const closeTimers = new WeakMap();
  let lastInteraction = 'mouse';

  const sideOf = (navigator) => (
    navigator.matches('.help-navigator, .release-navigator') ? 'right' : 'left'
  );
  const collapsedOn = (side) => navigators.filter((navigator) => (
    sideOf(navigator) === side && !navigator.classList.contains('is-open')
  ));
  const cancelConceal = (side = '') => {
    const sides = side ? [side] : ['left', 'right'];
    sides.forEach((item) => {
      window.clearTimeout(concealTimers[item]);
      concealTimers[item] = 0;
    });
  };
  const conceal = (side = '') => {
    navigators.forEach((navigator) => {
      if ((!side || sideOf(navigator) === side) && !navigator.classList.contains('is-open')) {
        navigator.classList.remove('is-edge-revealed');
      }
    });
  };
  const scheduleConceal = (side, delay = autoHideDelay) => {
    cancelConceal(side);
    concealTimers[side] = window.setTimeout(() => conceal(side), delay);
  };
  const reveal = (side, autoHideDelay = 0) => {
    const collapsed = collapsedOn(side);
    if (!collapsed.length) return false;
    cancelConceal(side);
    collapsed.forEach((navigator) => navigator.classList.add('is-edge-revealed'));
    if (autoHideDelay) scheduleConceal(side, autoHideDelay);
    return true;
  };
  const cancelClose = (navigator) => {
    window.clearTimeout(closeTimers.get(navigator));
    closeTimers.delete(navigator);
  };
  const closeNavigator = (navigator, forceBlur = false) => {
    cancelClose(navigator);
    navigator.classList.remove('is-open', 'is-edge-revealed');
    navigator.querySelector('[aria-expanded="true"]')?.setAttribute('aria-expanded', 'false');
    if (navigator.contains(document.activeElement) && (forceBlur || lastInteraction !== 'keyboard')) {
      document.activeElement?.blur();
    }
  };
  const shouldRemainOpen = (navigator) => (
    (lastInteraction === 'mouse' && navigator.matches(':hover'))
    || (lastInteraction === 'keyboard' && navigator.matches(':focus-within'))
  );
  const scheduleClose = (navigator, delay = autoHideDelay) => {
    cancelClose(navigator);
    if (!navigator.classList.contains('is-open')) return;
    closeTimers.set(navigator, window.setTimeout(() => {
      if (shouldRemainOpen(navigator)) scheduleClose(navigator);
      else closeNavigator(navigator);
    }, delay));
  };
  const hideAll = () => {
    cancelConceal();
    navigators.forEach((navigator) => closeNavigator(navigator, true));
    conceal();
  };

  navigators.forEach((navigator) => {
    let wasOpen = navigator.classList.contains('is-open');
    navigator.addEventListener('pointerenter', (event) => {
      lastInteraction = event.pointerType || 'mouse';
      cancelConceal(sideOf(navigator));
      cancelClose(navigator);
    });
    navigator.addEventListener('pointerleave', (event) => {
      if (event.pointerType !== 'mouse') return;
      scheduleConceal(sideOf(navigator));
      scheduleClose(navigator);
    });
    navigator.addEventListener('pointerdown', (event) => {
      lastInteraction = event.pointerType || 'mouse';
      if (navigator.classList.contains('is-open')) scheduleClose(navigator);
    });
    navigator.addEventListener('focusin', () => {
      if (lastInteraction === 'keyboard') cancelClose(navigator);
    });
    navigator.addEventListener('focusout', () => {
      window.setTimeout(() => {
        if (!navigator.matches(':focus-within')) scheduleClose(navigator);
      });
    });
    new MutationObserver(() => {
      const open = navigator.classList.contains('is-open');
      if (open) {
        cancelConceal(sideOf(navigator));
        scheduleClose(navigator);
      }
      else if (wasOpen && navigator.classList.contains('is-edge-revealed')) {
        cancelClose(navigator);
        scheduleConceal(sideOf(navigator));
      }
      wasOpen = open;
    }).observe(navigator, {attributes: true, attributeFilter: ['class']});
  });

  document.addEventListener('pointermove', (event) => {
    if (event.pointerType !== 'mouse') return;
    lastInteraction = 'mouse';
    const activationWidth = 44;
    if (event.clientX <= activationWidth) {
      reveal('left');
    } else if (event.clientX >= window.innerWidth - activationWidth) {
      reveal('right');
    } else if (!navigators.some((navigator) => navigator.matches(':hover'))) {
      scheduleConceal('left');
      scheduleConceal('right');
    }
  }, {passive: true});

  document.addEventListener('pointerdown', (event) => {
    lastInteraction = event.pointerType || 'mouse';
    if (!['touch', 'pen'].includes(event.pointerType)) return;
    const activationWidth = 30;
    const side = event.clientX <= activationWidth
      ? 'left'
      : (event.clientX >= window.innerWidth - activationWidth ? 'right' : '');
    if (!side) return;
    const collapsed = collapsedOn(side);
    if (!collapsed.length || collapsed.some((navigator) => navigator.contains(event.target))) return;
    if (reveal(side, autoHideDelay)) event.preventDefault();
  }, {capture: true, passive: false});

  document.addEventListener('keydown', () => { lastInteraction = 'keyboard'; }, {passive: true});
  window.addEventListener('scroll', hideAll, {passive: true});
  window.addEventListener('blur', hideAll, {passive: true});
}

// The Chart Viewer and the Report Template editor deliberately share this
// control surface. Keeping the filter builder and the searchable popovers in
// one component prevents the two previews from drifting apart.
function createInteractiveChartPreviewControls(fieldsElement, definition, options = {}) {
  if (!fieldsElement) return {definition: () => ({})};
  const fields = options.fields || [
    ['chart_type', 'Chart Type'], ['cdr_source', 'CDR Source'], ['kpi', 'KPI'], ['filters', 'Filters'],
    ['grouping_rows', 'Rows'], ['grouping_columns', 'Columns'], ['legend', 'Legend'], ['legend_position', 'Legend Position'],
    ['axis_x_range', 'Axis X Range'], ['axis_y_range', 'Axis Y Range'],
    ['label_position', 'Label Position'], ['label_format', 'Label Format'], ['exclude_null_empty', 'Exclude Null/Empty'], ['exclude_zero', 'Exclude Zero'],
  ];
  const multiFields = new Set(['dataset_ids', 'grouping_rows', 'grouping_columns', 'legend']);
  const parseKpiDefinition = (value) => {
    const text = String(value || '').trim();
    const match = text.match(/^\s*(SUM|COUNTD|COUNT|AVERAGE|AVG|MEAN|MAX|MIN|MEDIAN)\s*\(\s*(.+?)\s*\)\s*$/i);
    if (!match) return {field: text, operation: ''};
    const operation = match[1].toUpperCase();
    return {field: match[2].trim(), operation: ['AVG', 'MEAN'].includes(operation) ? 'AVERAGE' : operation};
  };
  const kpiDefinition = parseKpiDefinition(definition.kpi);
  const sourceKey = (source) => {
    const normalized = String(source || '').trim().toLowerCase();
    return ({data: 'cdr-data', voice: 'cdr-voice', speech: 'cdr-speech'})[normalized] || (normalized.startsWith('cdr-') ? normalized : `cdr-${normalized}`);
  };
  const columnsFor = (source) => Array.from(new Set((options.columnsBySource || {})[sourceKey(source)] || [])).sort((left, right) => left.localeCompare(right));
  const valuesFor = (value, key) => new Set(String(value || '').split(key === 'legend' ? ',' : /\s*×\s*|\s+\bx\b\s+/i).map((item) => item.trim()).filter(Boolean));
  const normalisePreviewValue = (value) => String(value || '').trim().toLocaleLowerCase().replace(/[^a-z0-9]+/g, '');
  const matchingPreviewValue = (requested, available) => (
    available.find((value) => normalisePreviewValue(value) === normalisePreviewValue(requested)) || requested
  );
  const orderedSelectedValues = (select) => {
    const selected = new Set(Array.from(select.selectedOptions).map((option) => option.value));
    let order = [];
    try { order = JSON.parse(select.dataset.previewSelectionOrder || '[]'); } catch (_error) { order = []; }
    order = order.filter((value) => selected.has(value));
    Array.from(selected).forEach((value) => { if (!order.includes(value)) order.push(value); });
    select.dataset.previewSelectionOrder = JSON.stringify(order);
    return order;
  };
  const currentDefinition = () => Object.fromEntries(Array.from(fieldsElement.querySelectorAll('[name]')).map((control) => {
    if (control.name === 'label_format' && fieldsElement.querySelector('[data-preview-label-format-automatic]')?.checked) return [control.name, ''];
    if (options.editableGroupingInputs && ['grouping_rows', 'grouping_columns'].includes(control.name)) {
      const editor = control.parentElement?.querySelector('[data-preview-grouping-text]');
      if (editor) return [control.name, editor.value.trim()];
    }
    if (!control.multiple) {
      const value = control.value || control.dataset.previewDisplay || '';
      if (control.name === 'kpi') {
        const operation = fieldsElement.querySelector('[data-preview-kpi-aggregation]')?.value || '';
        return [control.name, operation && value ? `${operation}(${value})` : value];
      }
      return [control.name, value];
    }
    return [control.name, orderedSelectedValues(control).join(control.name === 'legend' || control.name === 'dataset_ids' ? ', ' : ' × ')];
  }));
  let activeMenu = null;
  let activeMenuTrigger = null;
  let activeMenuHome = null;
  let activeMenuNextSibling = null;
  let closeTimer = null;
  const closeMenu = () => {
    if (closeTimer) window.clearTimeout(closeTimer);
    closeTimer = null;
    activeMenuTrigger?.setAttribute('aria-expanded', 'false');
    activeMenu?.setAttribute('hidden', '');
    if (activeMenu && activeMenuHome) activeMenuHome.insertBefore(activeMenu, activeMenuNextSibling);
    activeMenu = null; activeMenuTrigger = null; activeMenuHome = null; activeMenuNextSibling = null;
  };
  const setupSelects = (root = fieldsElement) => {
    // Filter-condition selects are dynamic and do not have a name. Include
    // them explicitly so Column and Operator receive the same searchable,
    // single-value dropdown used by KPI and CDR Source in every preview host.
    root.querySelectorAll('select[name], select[data-preview-kpi-aggregation], select[data-report-chart-filter-select], .report-chart-filter-condition select').forEach((select) => {
      if (select.classList.contains('report-chart-preview-select-native')) return;
      const shell = document.createElement('div'); shell.className = 'report-chart-preview-select';
      const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'report-chart-preview-select-trigger'; trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');
      trigger.disabled = select.disabled;
      const triggerText = document.createElement('span'); triggerText.className = 'report-chart-preview-select-value'; trigger.append(triggerText);
      const menu = document.createElement('div'); menu.className = 'report-chart-preview-select-menu'; menu.hidden = true;
      const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search values…'; search.setAttribute('aria-label', `Search ${select.getAttribute('aria-label') || 'values'}`);
      const menuOptions = document.createElement('div'); menuOptions.className = 'report-chart-preview-select-options';
      const syncTrigger = () => {
        const selected = Array.from(select.selectedOptions).map((option) => option.textContent?.trim()).filter(Boolean);
        const configured = select.dataset.previewDisplay || '';
        triggerText.textContent = select.multiple
          ? (selected.length ? `${selected.length} selected` : (configured ? `${configured.split(select.name === 'legend' || select.name === 'dataset_ids' ? ',' : /\s*×\s*|\s+\bx\b\s+/i).filter(Boolean).length} selected` : 'Select fields…'))
          : (selected[0] || configured || 'Select a value…');
      };
      const renderOptions = () => {
        const query = search.value.trim().toLocaleLowerCase();
        menuOptions.replaceChildren(...Array.from(select.options).filter((option) => !option.disabled && (!query || option.textContent.toLocaleLowerCase().includes(query))).map((option) => {
          if (select.multiple) {
            const item = document.createElement('label'); item.className = 'report-chart-preview-select-option is-multiple';
            const input = document.createElement('input'); input.type = 'checkbox'; input.checked = option.selected;
            const text = document.createElement('span'); text.textContent = option.textContent;
            input.addEventListener('change', () => { option.selected = input.checked; let order = orderedSelectedValues(select); order = input.checked ? [...order.filter((value) => value !== option.value), option.value] : order.filter((value) => value !== option.value); select.dataset.previewSelectionOrder = JSON.stringify(order); select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); });
            item.append(input, text); return item;
          }
          const item = document.createElement('button'); item.type = 'button'; item.className = 'report-chart-preview-select-option'; item.textContent = option.textContent; item.setAttribute('aria-selected', String(option.selected));
          item.addEventListener('click', () => { select.value = option.value; select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); closeMenu(); });
          return item;
        }));
        if (!menuOptions.childElementCount) { const empty = document.createElement('p'); empty.className = 'report-chart-preview-select-empty'; empty.textContent = 'No matching values'; menuOptions.append(empty); }
      };
      if (select.multiple) {
        const actions = document.createElement('div'); actions.className = 'report-chart-preview-select-actions';
        const toggleAll = document.createElement('button'); toggleAll.type = 'button'; toggleAll.textContent = 'Select all / none';
        toggleAll.addEventListener('click', () => { const selectable = Array.from(select.options).filter((option) => !option.disabled); const selectAll = selectable.some((option) => !option.selected); selectable.forEach((option) => { option.selected = selectAll; }); select.dataset.previewSelectionOrder = JSON.stringify(selectAll ? selectable.map((option) => option.value) : []); select.dispatchEvent(new Event('change', {bubbles: true})); select.dispatchEvent(new Event('input', {bubbles: true})); syncTrigger(); renderOptions(); });
        actions.append(toggleAll); menu.append(search, actions, menuOptions);
      } else menu.append(search, menuOptions);
      search.addEventListener('input', renderOptions);
      const toggleMenu = () => {
        if (activeMenu === menu) { closeMenu(); return; }
        closeMenu(); renderOptions();
        // Some hosts use a backdrop that creates a new fixed-positioning
        // context. Each caller can therefore choose the visible dialog layer
        // that owns its popup; the template editor deliberately uses body.
        activeMenuHome = menu.parentNode;
        activeMenuNextSibling = menu.nextSibling;
        (options.menuContainer || document.body).append(menu);
        menu.hidden = false; activeMenu = menu; activeMenuTrigger = trigger; trigger.setAttribute('aria-expanded', 'true');
        const bounds = trigger.getBoundingClientRect(); menu.style.left = `${Math.max(8, Math.min(bounds.left, window.innerWidth - 380))}px`; menu.style.top = `${Math.min(bounds.bottom + 4, window.innerHeight - 310)}px`; search.focus();
      };
      trigger.addEventListener('click', toggleMenu);
      trigger.addEventListener('keydown', (event) => { if (['Enter', ' ', 'ArrowDown'].includes(event.key)) { event.preventDefault(); toggleMenu(); } });
      shell.addEventListener('mouseenter', () => { if (closeTimer) window.clearTimeout(closeTimer); });
      shell.addEventListener('mouseleave', () => { if (closeTimer) window.clearTimeout(closeTimer); closeTimer = window.setTimeout(() => { if (activeMenu === menu) closeMenu(); }, 550); });
      menu.addEventListener('mouseenter', () => { if (closeTimer) window.clearTimeout(closeTimer); });
      menu.addEventListener('mouseleave', () => { if (closeTimer) window.clearTimeout(closeTimer); closeTimer = window.setTimeout(() => { if (activeMenu === menu) closeMenu(); }, 550); });
      select.classList.add('report-chart-preview-select-native'); select.after(shell); shell.append(trigger, menu); select.addEventListener('input', syncTrigger); select.addEventListener('change', syncTrigger); select.addEventListener('preview-selection-change', syncTrigger); syncTrigger();
    });
  };
  document.addEventListener('click', (event) => {
    if (activeMenu && !activeMenu.contains(event.target) && !activeMenuTrigger?.closest('.report-chart-preview-select')?.contains(event.target)) closeMenu();
  });
  fieldsElement.replaceChildren(...fields.map(([key, label]) => {
    const field = document.createElement('label'); field.dataset.previewField = key; field.textContent = label;
    if (options.textFields?.[key] || key === 'axis_x_range' || key === 'axis_y_range') {
      const control = document.createElement('input');
      control.type = 'text'; control.name = key; control.value = definition[key] || ''; control.setAttribute('aria-label', label);
      field.append(control); return field;
    }
    if (key === 'filters') {
      const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = 'filters';
      const builder = document.createElement('div'); builder.className = 'report-chart-filter-builder';
      const conditions = document.createElement('div'); conditions.className = 'report-chart-filter-conditions';
      const parsedField = document.createElement('input'); parsedField.type = 'text'; parsedField.className = 'report-chart-preview-parsed'; parsedField.readOnly = true; parsedField.placeholder = 'No filters applied'; parsedField.setAttribute('aria-label', 'Applied filters');
      const sync = () => { hidden.value = Array.from(conditions.children).map((row) => { const [column, operator] = row.querySelectorAll('select'); const value = row.querySelector('[data-report-chart-filter-value]'); const rawValue = value?.value.trim(); const parserValue = ['IN', 'NOT IN'].includes(operator?.value) && rawValue && !/^\(.*\)$/.test(rawValue) ? `(${rawValue})` : rawValue; return column?.value && operator?.value && parserValue ? `${column.value} ${operator.value} ${parserValue}` : ''; }).filter(Boolean).join('; '); parsedField.value = hidden.value; hidden.dispatchEvent(new Event('input')); };
      const addCondition = (condition = {}) => {
        const row = document.createElement('div'); row.className = 'report-chart-filter-condition';
        const column = document.createElement('select'); column.add(new Option('Column…', '')); column.dataset.reportChartFilterSelect = ''; column.setAttribute('aria-label', 'Filter column');
        const filterColumns = Array.from(new Set([condition.column || '', ...columnsFor(definition.cdr_source)].filter(Boolean)));
        const selectedColumn = matchingPreviewValue(condition.column, filterColumns);
        filterColumns.forEach((value) => column.add(new Option(value, value, false, value === selectedColumn)));
        const operator = document.createElement('select'); operator.dataset.reportChartFilterSelect = ''; operator.setAttribute('aria-label', 'Filter operator'); ['=', '!=', 'CONTAINS', 'NOT CONTAINS', 'IN', 'NOT IN', '>=', '<=', '>', '<'].forEach((value) => operator.add(new Option(value, value, false, value === condition.operator)));
        const value = document.createElement('input'); value.type = 'text'; value.dataset.reportChartFilterValue = ''; value.placeholder = 'Value';
        // Preserve both the attribute and live property. Some browsers reset
        // the live value while the nearby custom select controls are mounted.
        const filterValue = String(condition.value ?? '');
        value.defaultValue = filterValue; value.value = filterValue; value.setAttribute('value', filterValue);
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '−'; remove.title = 'Remove condition'; remove.addEventListener('click', () => { row.remove(); sync(); });
        [column, operator, value].forEach((input) => { input.addEventListener('input', sync); input.addEventListener('change', sync); }); row.append(column, operator, value, remove); conditions.append(row); setupSelects(row);
        value.value = filterValue;
      };
      const parsed = String(definition.filters || '').split(';').map((item) => item.trim()).filter(Boolean).map((item) => { const match = item.match(/^(.+?)\s+(NOT\s+CONTAINS|NOT\s+IN|CONTAINS|IN|>=|<=|!=|=|>|<)\s+(.+)$/i); return match ? {column: match[1].trim(), operator: match[2].toUpperCase(), value: match[3].trim()} : {}; });
      (parsed.length ? parsed : [{}]).forEach(addCondition);
      const add = document.createElement('button'); add.type = 'button'; add.className = 'report-chart-filter-add'; add.textContent = '+ Add condition'; add.addEventListener('click', () => addCondition());
      builder.append(conditions, add); field.append(hidden, builder, parsedField);
      // The initial definition is authoritative. Do not derive it from the
      // just-created controls before their custom select widgets have settled.
      hidden.value = String(definition.filters || ''); parsedField.value = hidden.value;
      return field;
    }
    if (key === 'label_format') {
      const control = document.createElement('input');
      control.type = 'hidden'; control.name = key; control.value = String(definition[key] || '');
      const opener = document.createElement('button'); opener.type = 'button'; opener.className = 'report-chart-label-format-trigger';
      const assistance = document.createElement('fieldset'); assistance.className = 'report-chart-label-format-assistance'; assistance.hidden = true;
      const legend = document.createElement('legend'); legend.textContent = 'Label format';
      const color = document.createElement('input'); color.type = 'color'; color.value = '#FFFFFF'; color.setAttribute('aria-label', 'Label format color');
      const colorValue = document.createElement('output');
      const colorRow = document.createElement('span'); colorRow.className = 'catalogue-label-format-colour-row'; colorRow.append(color, colorValue);
      const colorLabel = document.createElement('label'); colorLabel.textContent = 'Color'; colorLabel.append(colorRow);
      const fontChoice = document.createElement('select'); ['Arial', 'Helvetica', 'Verdana', 'Tahoma', 'Georgia', 'Times New Roman', 'Courier New'].forEach((value) => fontChoice.add(new Option(value)));
      const fontLabel = document.createElement('label'); fontLabel.textContent = 'Font'; fontLabel.append(fontChoice);
      const sizeChoice = document.createElement('select'); ['Small', 'Medium', 'Large'].forEach((value) => sizeChoice.add(new Option(value)));
      const sizeLabel = document.createElement('label'); sizeLabel.textContent = 'Size'; sizeLabel.append(sizeChoice);
      const styles = document.createElement('div'); styles.className = 'catalogue-label-format-styles'; styles.setAttribute('role', 'group'); styles.setAttribute('aria-label', 'Text styles');
      const styleControls = {};
      ['Bold', 'Italic', 'Underline'].forEach((style) => {
        const choice = document.createElement('input'); choice.type = 'checkbox';
        const styleLabel = document.createElement('label'); const text = document.createElement('span'); text.textContent = style;
        styleLabel.append(choice, text); styles.append(styleLabel); styleControls[style] = choice;
      });
      const automatic = document.createElement('button'); automatic.type = 'button'; automatic.className = 'report-chart-label-format-automatic'; automatic.textContent = 'Use automatic format';
      const parseTokens = () => {
        try { const parsed = JSON.parse(control.value || '[]'); return Array.isArray(parsed) ? parsed : []; } catch (_error) { return []; }
      };
      const hydrate = () => {
        const tokens = parseTokens(); const configured = tokens.length > 0;
        color.value = tokens.find((value) => /^#[0-9a-f]{6}$/i.test(value)) || '#FFFFFF';
        colorValue.textContent = color.value.toUpperCase();
        fontChoice.value = tokens.find((value) => Array.from(fontChoice.options).some((option) => option.value === value)) || 'Arial';
        sizeChoice.value = tokens.find((value) => ['Small', 'Medium', 'Large'].includes(value)) || 'Medium';
        Object.entries(styleControls).forEach(([style, choice]) => { choice.checked = tokens.includes(style); });
        opener.textContent = configured ? [color.value.toUpperCase(), fontChoice.value, sizeChoice.value, ...Object.entries(styleControls).filter(([, choice]) => choice.checked).map(([style]) => style)].join(' · ') : 'Automatic format';
      };
      const applyFormat = () => {
        control.value = JSON.stringify([color.value.toUpperCase(), fontChoice.value, sizeChoice.value, ...Object.entries(styleControls).filter(([, choice]) => choice.checked).map(([style]) => style)]);
        hydrate(); control.dispatchEvent(new Event('input'));
      };
      [color, fontChoice, sizeChoice, ...Object.values(styleControls)].forEach((choice) => choice.addEventListener('input', applyFormat));
      automatic.addEventListener('click', () => { control.value = ''; hydrate(); control.dispatchEvent(new Event('input')); });
      opener.addEventListener('click', () => { assistance.hidden = !assistance.hidden; if (!assistance.hidden) color.focus(); });
      assistance.append(legend, colorLabel, fontLabel, sizeLabel, styles, automatic);
      field.append(control, opener, assistance); hydrate(); return field;
    }
    const control = document.createElement('select');
    if (key === 'chart_type') (options.chartTypes || []).forEach((value) => control.add(new Option(value, value, false, normalisePreviewValue(value) === normalisePreviewValue(definition[key]))));
    else if (key === 'cdr_source') (options.cdrSources || ['CDR-Data', 'CDR-Voice', 'CDR-Speech']).forEach((value) => control.add(new Option(value, value, false, sourceKey(value) === sourceKey(definition[key]))));
    else if (key === 'dataset_ids') {
      control.multiple = true;
      const selected = new Set(Array.isArray(definition[key]) ? definition[key].map(String) : String(definition[key] || '').split(',').map((value) => value.trim()).filter(Boolean));
      (options.datasetsBySource?.[sourceKey(definition.cdr_source)] || []).forEach((dataset) => control.add(new Option(dataset.label, String(dataset.value), false, selected.has(String(dataset.value)))));
    }
    else if (key === 'legend_position') (options.legendPositions || ['', 'Top', 'Bottom', 'Left', 'Right']).forEach((value) => control.add(new Option(value || 'No legend position', value, false, normalisePreviewValue(value) === normalisePreviewValue(definition[key]))));
    else if (key === 'label_position') (options.labelPositions || ['', 'None', 'Top', 'Up', 'Middle', 'Down']).forEach((value) => control.add(new Option(value || 'Automatic', value, false, normalisePreviewValue(value) === normalisePreviewValue(definition[key]))));
    else if (key === 'exclude_null_empty' || key === 'exclude_zero') {
      const enabled = definition[key] === true || ['yes', 'true', '1'].includes(String(definition[key] || '').trim().toLocaleLowerCase());
      const keepLabel = key === 'exclude_null_empty' ? 'Keep null/empty values' : 'Keep zero values';
      control.add(new Option(keepLabel, '', false, !enabled));
      control.add(new Option('Yes', 'Yes', false, enabled));
    }
    else {
      const available = columnsFor(definition.cdr_source);
      const definitionValue = key === 'kpi' ? kpiDefinition.field : definition[key];
      const configuredValues = multiFields.has(key)
        ? Array.from(valuesFor(definitionValue, key))
        : [String(definitionValue || '').trim()].filter(Boolean);
      const selected = new Set(configuredValues.map((value) => matchingPreviewValue(value, available)));
      if (multiFields.has(key)) control.multiple = true; else control.add(new Option('Choose a field…', ''));
      Array.from(new Set([...selected, ...available])).filter(Boolean).forEach((value) => control.add(new Option(value, value, false, selected.has(value))));
    }
    // Explicit assignment is needed after dynamic menu reconstruction: a
    // browser can otherwise retain the blank placeholder selected even when
    // the option was initially marked selected by the constructor.
    if (control.multiple) {
      const requested = key === 'dataset_ids'
        ? new Set(Array.isArray(definition[key]) ? definition[key].map(String) : String(definition[key] || '').split(',').map((value) => value.trim()).filter(Boolean))
        : valuesFor(definition[key], key);
      Array.from(control.options || []).forEach((option) => {
        option.selected = Array.from(requested).some((value) => normalisePreviewValue(value) === normalisePreviewValue(option.value));
      });
    } else {
      const definitionValue = key === 'kpi' ? kpiDefinition.field : definition[key];
      const requested = key === 'cdr_source' ? sourceKey(definitionValue) : normalisePreviewValue(definitionValue);
      const matching = Array.from(control.options || []).find((option) => (
        key === 'cdr_source' ? sourceKey(option.value) === requested : normalisePreviewValue(option.value) === requested
      ));
      if (matching) control.value = matching.value;
    }
    if (control.multiple) {
      const requestedOrder = key === 'dataset_ids'
        ? (Array.isArray(definition[key]) ? definition[key].map(String) : String(definition[key] || '').split(',').map((value) => value.trim()).filter(Boolean))
        : Array.from(valuesFor(definition[key], key));
      control.dataset.previewSelectionOrder = JSON.stringify(requestedOrder.map((value) => matchingPreviewValue(value, Array.from(control.options || []).map((option) => option.value))));
    }
    const definitionValue = key === 'kpi' ? kpiDefinition.field : definition[key];
    control.name = key; control.dataset.previewDisplay = String(definitionValue || ''); control.setAttribute('aria-label', label); field.append(control);
    if (key === 'kpi') {
      const operationLabel = document.createElement('span'); operationLabel.className = 'report-chart-preview-subfield-label'; operationLabel.textContent = 'KPI operation';
      const operation = document.createElement('select'); operation.dataset.previewKpiAggregation = ''; operation.setAttribute('aria-label', 'KPI operation');
      [
        ['', 'Chart default'], ['SUM', 'SUM'], ['COUNT', 'COUNT'], ['COUNTD', 'COUNTD'],
        ['AVERAGE', 'AVERAGE / MEAN'], ['MAX', 'MAX'], ['MIN', 'MIN'], ['MEDIAN', 'MEDIAN'],
      ].forEach(([value, text]) => operation.add(new Option(text, value, false, value === kpiDefinition.operation)));
      operation.value = kpiDefinition.operation;
      field.append(operationLabel, operation);
    }
    if (key === 'grouping_rows' || key === 'grouping_columns') {
      const parsed = document.createElement('input'); parsed.type = 'text'; parsed.className = 'report-chart-preview-parsed'; parsed.readOnly = !options.editableGroupingInputs; parsed.dataset.previewGroupingText = ''; parsed.placeholder = `No ${label.toLowerCase()} selected`; parsed.setAttribute('aria-label', `Selected ${label.toLowerCase()}`);
      const syncParsed = () => { parsed.value = orderedSelectedValues(control).join(' × '); };
      control.addEventListener('input', syncParsed); control.addEventListener('change', syncParsed); syncParsed(); field.append(parsed);
      if (options.editableGroupingInputs) parsed.addEventListener('input', () => {
        const requested = Array.from(valuesFor(parsed.value, key));
        const available = Array.from(control.options).map((option) => option.value);
        const selected = requested.map((value) => matchingPreviewValue(value, available));
        Array.from(control.options).forEach((option) => { option.selected = selected.includes(option.value); });
        control.dataset.previewSelectionOrder = JSON.stringify(selected);
        control.dataset.previewDisplay = parsed.value.trim();
        // Updating the native select must not emit its input event: that event
        // also normalizes the editable expression from selected options and
        // would erase text the user has just entered but has not completed.
        control.dispatchEvent(new Event('preview-selection-change'));
        options.onChange?.(currentDefinition());
      });
    }
    return field;
  }));
  const syncConditionalVisualControls = () => {
    const applicability = {
      axis_x_range: true,
      axis_y_range: true,
      label_position: true,
    };
    Object.entries(applicability).forEach(([name, enabled]) => {
      const control = fieldsElement.querySelector(`[name="${name}"]`);
      if (!control) return;
      if (!enabled) {
        control.value = '';
        control.dataset.previewDisplay = '';
      }
      control.disabled = !enabled;
      const field = control.closest('[data-preview-field]');
      field?.classList.toggle('is-inapplicable', !enabled);
      if (field) field.title = enabled ? '' : 'Not available for this chart type.';
      const trigger = control.nextElementSibling?.querySelector('.report-chart-preview-select-trigger');
      if (trigger) trigger.disabled = !enabled;
    });
  };
  syncConditionalVisualControls();
  setupSelects();
  syncConditionalVisualControls();
  fieldsElement.querySelector('[name="cdr_source"]')?.addEventListener('change', () => options.onSourceChange?.(currentDefinition()));
  fieldsElement.querySelectorAll('[name]').forEach((control) => control.addEventListener('input', () => {
    if (control.name === 'chart_type') syncConditionalVisualControls();
    options.onChange?.(currentDefinition());
  }));
  fieldsElement.querySelectorAll('select[name]').forEach((control) => control.addEventListener('change', () => {
    if (control.name === 'chart_type') syncConditionalVisualControls();
    options.onChange?.(currentDefinition());
  }));
  const kpiAggregation = fieldsElement.querySelector('[data-preview-kpi-aggregation]');
  kpiAggregation?.addEventListener('input', () => options.onChange?.(currentDefinition()));
  kpiAggregation?.addEventListener('change', () => options.onChange?.(currentDefinition()));
  return {definition: currentDefinition, close: closeMenu};
}

function hideLoadingOverlay() {
  if (!loadingOverlay) return;
  loadingOverlay.hidden = true;
  if (loadingCancel instanceof HTMLButtonElement) { loadingCancel.hidden = true; loadingCancel.onclick = null; loadingCancel.disabled = false; }
  document.body.classList.remove('loading-active');
}

function showLoadingOverlay(label, copy) {
  if (!loadingOverlay) return;
  loadingTitle.textContent = label || 'Processing request';
  loadingCopy.textContent = copy || 'Please wait while the workspace processes the selected dataset or updates the analysis.';
  if (loadingCancel instanceof HTMLButtonElement) { loadingCancel.hidden = true; loadingCancel.onclick = null; loadingCancel.disabled = false; }
  if (loadingProgressBar instanceof HTMLElement) {
    loadingProgressBar.style.width = '45%';
    loadingProgressBar.style.animation = '';
  }
  loadingOverlay.hidden = false;
  document.body.classList.add('loading-active');
}

function setLoadingProgress(progress) {
  if (!(loadingProgressBar instanceof HTMLElement)) return;
  const numericProgress = Number(progress);
  if (!Number.isFinite(numericProgress) || numericProgress <= 0) {
    loadingProgressBar.style.width = '45%';
    loadingProgressBar.style.animation = '';
    return;
  }
  loadingProgressBar.style.width = `${Math.min(100, Math.max(0, numericProgress))}%`;
  loadingProgressBar.style.animation = 'none';
}

hideLoadingOverlay();
window.addEventListener('pageshow', hideLoadingOverlay);

function resolveDownloadFilename(response, fallbackName) {
  const disposition = response.headers.get('content-disposition') || '';
  const utf8Match = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (_error) {
      return utf8Match[1];
    }
  }
  const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
  return match ? match[1] : fallbackName;
}

async function submitDownloadForm(form) {
  showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
  try {
    const method = String(form.method || 'post').toUpperCase();
    const formData = new FormData(form);
    const requestUrl = method === 'GET'
      ? `${form.action}${form.action.includes('?') ? '&' : '?'}${new URLSearchParams(formData).toString()}`
      : form.action;
    const response = await fetch(requestUrl, method === 'GET' ? {
      method,
      credentials: 'same-origin',
    } : {
      method,
      body: formData,
      credentials: 'same-origin',
    });
    if (!response.ok) {
      hideLoadingOverlay();
      alert(`Download failed with status ${response.status}.`);
      return;
    }
    const blob = await response.blob();
    const fallbackName = form.action.includes('/import-export/export')
      ? 'dashboard-analytic-export.zip'
      : (form.action.includes('/powerpoint') ? 'report.pptx' : 'report.docx');
    const filename = resolveDownloadFilename(response, fallbackName);
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
  } catch (_error) {
    alert('Download failed. Please try again.');
  } finally {
    hideLoadingOverlay();
  }
}

if (window.location.pathname === '/datasets-analysis') {
  const params = new URLSearchParams(window.location.search);
  const persistedDatasetsAnalysisQuery = getPersistedDatasetsAnalysisQuery(params);
  if (params.get('dataset_id')) {
    persistActiveDatasetState(params);
  }
  if (hasMeaningfulDatasetsAnalysisState(params)) {
    persistDatasetsAnalysisState(params);
  } else if (persistedDatasetsAnalysisQuery) {
    replaceLocation(buildRestoredDatasetsAnalysisUrl(params, persistedDatasetsAnalysisQuery));
  }
}

if (window.location.pathname === '/workspace') {
  const params = new URLSearchParams(window.location.search);
  if (params.get('dataset_id')) {
    persistActiveDatasetState(params);
  } else {
    const activeDataset = restoreActiveDatasetState();
    if (activeDataset?.dataset_id) {
      params.set('dataset_id', activeDataset.dataset_id);
      if (activeDataset.input_kind) {
        params.set('input_kind', activeDataset.input_kind);
      }
      replaceLocation(`/workspace?${params.toString()}`);
    }
  }
}

setupPersistentControls();
setupPersistentPanelState();
setupWorkspaceUserPickers();
setupCustomMultiSelects();
setupPagePanelNavigator();
setupModuleNavigator();
setupEdgeNavigatorReveal();
setupSearchableSingleSelects();

function maybeSyncPersistedGlobalDatasetsAnalysisSelectors() {
  if (window.location.pathname !== '/datasets-analysis' || hasPendingLocationRestore) return;
  const aggregationSelect = document.querySelector('[data-global-aggregation-select]');
  const cdfSelect = document.querySelector('[data-global-cdf-grouping-select]');
  if (!aggregationSelect && !cdfSelect) return;

  const params = new URLSearchParams(window.location.search);
  let shouldReplace = false;

  const persistedAggregation = aggregationSelect ? getPersistedControlValue(aggregationSelect) : null;
  if (
    aggregationSelect &&
    persistedAggregation &&
    persistedAggregation !== 'all' &&
    String(params.get('aggregation') || '').trim().toLowerCase() === 'all'
  ) {
    params.set('aggregation', persistedAggregation);
    shouldReplace = true;
  }

  const persistedCdfGrouping = cdfSelect ? getPersistedControlValue(cdfSelect) : null;
  if (
    cdfSelect &&
    persistedCdfGrouping &&
    persistedCdfGrouping !== 'all' &&
    String(params.get('cdf_grouping') || '').trim().toLowerCase() === 'all'
  ) {
    params.set('cdf_grouping', persistedCdfGrouping);
    shouldReplace = true;
  }

  if (!shouldReplace) return;
  if (!params.get('load')) {
    params.set('load', '1');
  }
  replaceLocation(`/datasets-analysis?${params.toString()}`);
}

maybeSyncPersistedGlobalDatasetsAnalysisSelectors();

function importWarningDetails(payload) {
  const kind = String(payload.kind || '');
  const collisions = Array.isArray(payload.workspace_collisions) ? payload.workspace_collisions : [];
  if (kind === 'bundle') {
    const collisionCopy = collisions.length
      ? ` Existing workspaces that will be replaced: ${collisions.join(', ')}.` : '';
    return {
      title: 'Import selected content?',
      message: `Every package in this export selection will be imported in order.${collisionCopy}${payload.requires_destination_workspaces ? ' Next, choose the destination workspaces for its workspace elements.' : ''}`,
    };
  }
  if (kind === 'config') {
    return payload.includes_slides_templates
      ? {
        title: 'Overwrite configuration and templates?',
        message: 'This will overwrite the configuration files and Report Templates included in the package. The local workspace registry and existing workspaces will be preserved.',
      }
      : {
        title: 'Overwrite configuration?',
        message: 'This will overwrite the configuration files included in the package. The local workspace registry and existing workspaces will be preserved.',
      };
  }
  if (kind === 'slides-templates') {
    return {
      title: 'Overwrite Report Templates?',
      message: 'Choose the destination workspaces next. Templates with matching names will be overwritten only in those workspaces. Importing templates does not rebuild CDR tables.',
    };
  }
  if (kind === 'dashboards') {
    return {
      title: 'Import Dashboards?',
      message: 'Choose the destination workspaces next. The original workspace is preselected when it exists. Dashboard definitions and saved filters will be replaced in those workspaces; generated caches are not imported.',
    };
  }
  if (kind === 'operator-mappings') {
    return {
      title: 'Overwrite Operator/Vendor Mappings & Colors?',
      message: 'Choose the destination workspaces next. Their complete Operator and Vendor aliases, order and theme colors will be replaced. Stored CDR values will not be modified or rematerialized.',
    };
  }
  if (kind === 'auto-calculated-fields') {
    return {
      title: 'Import Auto-calculated Fields?',
      message: 'Choose the destination workspaces next. Existing fields with the same name will be updated, new fields will be added, and applicable CDR tables will be materialized in the background without creating duplicate columns.',
    };
  }
  if (kind === 'workspace') {
    const name = collisions[0];
    return name
      ? {
        title: 'Overwrite workspace?',
        message: `Workspace "${name}" already exists and will be permanently replaced by the imported workspace.`,
      }
      : {
        title: 'Import workspace?',
        message: 'A new workspace will be created from this package.',
      };
  }
  const collisionCopy = collisions.length
    ? ` The following existing workspaces will be permanently replaced: ${collisions.join(', ')}.`
    : ' New workspaces will be created from the package.';
  return {
    title: 'Overwrite full environment?',
    message: `This will overwrite the configuration files and Report Templates included in the package.${collisionCopy} The local workspace registry will be rebuilt from the imported workspaces.`,
  };
}

function selectAutoCalculatedFieldWorkspaces(workspaces, kind = 'auto-calculated-fields', selectedIds = []) {
  if (!Array.isArray(workspaces) || !workspaces.length) {
    showInfoDialog('There are no destination workspaces available.', {title: 'Auto-calculated Fields', tone: 'error'});
    return Promise.resolve(null);
  }
  const overlay = document.createElement('div'); overlay.className = 'confirm-overlay incoming-transfer-confirm';
  const panel = document.createElement('section'); panel.className = 'confirm-panel auto-calculated-field-workspace-dialog';
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
  const title = document.createElement('h3'); title.textContent = 'Select destination workspaces';
  const copy = document.createElement('p'); copy.textContent = kind === 'slides-templates'
    ? 'Templates will be imported into every selected workspace. The original workspace is preselected when it exists. Matching template names will be overwritten.'
    : kind === 'dashboards'
      ? 'Dashboard definitions and their saved filters will replace the Dashboard list in every selected workspace. The original workspace is preselected when present; generated caches are not imported.'
      : kind === 'operator-mappings'
        ? 'The complete Operator/Vendor mapping and color configuration will replace aliases, order and theme colors in every selected workspace. Stored CDR values will remain unchanged.'
      : kind === 'bundle'
        ? 'Workspace elements in the selection will be imported into every selected workspace. Full Workspace packages keep their own workspace identity.'
        : 'The original workspace is preselected when present. Fields will be merged into every selected workspace; matching field names will be replaced.';
  const toolbar = document.createElement('div'); toolbar.className = 'full-environment-workspace-toolbar';
  const selectAll = document.createElement('button'); selectAll.type = 'button'; selectAll.className = 'ghost-link'; selectAll.textContent = 'Select all';
  const selectNone = document.createElement('button'); selectNone.type = 'button'; selectNone.className = 'ghost-link'; selectNone.textContent = 'Select none'; toolbar.append(selectAll, selectNone);
  const list = document.createElement('div'); list.className = 'full-environment-workspace-list';
  workspaces.forEach((workspace) => {
    const label = document.createElement('label'); label.className = 'full-environment-workspace-choice';
    const input = document.createElement('input'); input.type = 'checkbox'; input.value = workspace.id; input.checked = selectedIds.includes(workspace.id);
    const name = document.createElement('span'); name.textContent = workspace.name; label.append(input, name); list.append(label);
  });
  const error = document.createElement('p'); error.className = 'full-environment-workspace-error'; error.textContent = 'Select at least one workspace.'; error.hidden = true;
  const actions = document.createElement('div'); actions.className = 'confirm-actions';
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'ghost-link confirm-cancel'; cancel.textContent = 'Cancel';
  const accept = document.createElement('button'); accept.type = 'button'; accept.textContent = 'Use selected workspaces'; actions.append(cancel, accept);
  panel.append(title, copy, toolbar, list, error, actions); overlay.append(panel); document.body.append(overlay);
  document.body.classList.add('loading-active');
  return new Promise((resolve) => {
    const close = (value) => { overlay.remove(); document.body.classList.remove('loading-active'); resolve(value); };
    selectAll.addEventListener('click', () => { list.querySelectorAll('input').forEach((input) => { input.checked = true; }); error.hidden = true; });
    selectNone.addEventListener('click', () => { list.querySelectorAll('input').forEach((input) => { input.checked = false; }); });
    cancel.addEventListener('click', () => close(null));
    accept.addEventListener('click', () => {
      const selected = [...list.querySelectorAll('input:checked')].map((input) => input.value);
      if (!selected.length) { error.hidden = false; return; }
      close(selected);
    });
    overlay.addEventListener('click', (event) => { if (event.target === overlay) close(null); });
    accept.focus();
  });
}

function formatImportUploadBytes(bytes) {
  const numeric = Number(bytes);
  if (!Number.isFinite(numeric) || numeric < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = numeric;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function uploadImportPackage(file) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/admin/import-export/inspect/upload', true);
    request.withCredentials = true;
    request.setRequestHeader('Accept', 'application/json');
    request.setRequestHeader('Content-Type', file.type || 'application/zip');
    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return;
      const progress = event.total ? (event.loaded / event.total) * 100 : 0;
      setLoadingProgress(progress);
      if (loadingCopy) {
        loadingCopy.textContent = `Uploading ${formatImportUploadBytes(event.loaded)} of ${formatImportUploadBytes(event.total)} — ${Math.round(progress)}%.`;
      }
    });
    request.addEventListener('load', () => {
      let payload = {};
      try { payload = JSON.parse(request.responseText || '{}'); } catch (_error) { /* Handled below. */ }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(payload.detail || 'The selected file is not a valid export package.'));
        return;
      }
      resolve({payload, uploadId: request.getResponseHeader('X-Import-Upload-Id')});
    });
    request.addEventListener('error', () => reject(new Error('The import package upload was interrupted.')));
    request.addEventListener('abort', () => reject(new Error('The import package upload was cancelled.')));
    request.send(file);
  });
}

document.querySelectorAll('[data-import-package-form]').forEach((form) => {
  const confirmed = form.querySelector('[data-import-package-confirmed]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!(form instanceof HTMLFormElement) || !(confirmed instanceof HTMLInputElement)) return;
    if (!form.reportValidity()) return;
    const packageInput = form.querySelector('input[type="file"][name="package"]');
    const packageFile = packageInput instanceof HTMLInputElement ? packageInput.files?.[0] : null;
    if (!packageFile) return;
    confirmed.value = '0';
    showLoadingOverlay(
      'Uploading import package',
      'Uploading the selected ZIP package for inspection. Large workspace packages can take several minutes; the import warning will appear as soon as the upload is ready.',
    );
    try {
      // Let the browser paint the progress dialog before starting a potentially large upload.
      await new Promise((resolve) => window.requestAnimationFrame(resolve));
      const {payload, uploadId} = await uploadImportPackage(packageFile);
      if (!uploadId) throw new Error('The uploaded package could not be retained for import.');
      setLoadingProgress(100);
      if (loadingCopy) loadingCopy.textContent = 'Upload complete. Inspecting the package…';
      const warning = importWarningDetails(payload);
      hideLoadingOverlay();
      const accepted = await showConfirmDialog(warning.message, {
        title: warning.title,
        confirmLabel: 'Import and overwrite',
      });
      if (!accepted) {
        await fetch(`/admin/import-export/import/uploads/${encodeURIComponent(uploadId)}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        }).catch(() => {});
        return;
      }
      const destinationWorkspaceIds = payload.requires_destination_workspaces
        ? await selectAutoCalculatedFieldWorkspaces(payload.destination_workspaces, payload.kind, payload.selected_workspace_ids || [])
        : [];
      if (payload.requires_destination_workspaces && !destinationWorkspaceIds) {
        await fetch(`/admin/import-export/import/uploads/${encodeURIComponent(uploadId)}`, {
          method: 'DELETE', credentials: 'same-origin',
        }).catch(() => {});
        return;
      }
      confirmed.value = '1';
      showLoadingOverlay('Importing package', 'Please wait while Dashboard Analytic imports the selected package.');
      const importData = new FormData();
      importData.set('upload_id', uploadId);
      importData.set('confirmed_import', 'true');
      destinationWorkspaceIds.forEach((workspaceId) => importData.append('workspace_ids', workspaceId));
      const importResponse = await fetch('/admin/import-export/import/jobs', {
        method: 'POST',
        body: importData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const importPayload = await importResponse.json().catch(() => ({}));
      if (!importResponse.ok || !importPayload.status_url) {
        throw new Error(importPayload.detail || 'The import could not be started.');
      }
      const isBackgroundFieldImport = payload.kind === 'auto-calculated-fields';
      if (isBackgroundFieldImport) {
        hideLoadingOverlay();
        showInfoDialog(
          'The fields are being imported and materialized in the selected workspaces in the background. You can continue working; a notification will appear when the process finishes.',
          {title: 'Auto-calculated Fields import started'},
        );
      }
      const pollImport = async () => {
        const statusResponse = await fetch(importPayload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const status = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(status.detail || 'The import status could not be read.');
        if (status.status === 'ready') {
          if (isBackgroundFieldImport) {
            showInfoDialog(status.notice || 'Auto-calculated Fields imported successfully.', {title: 'Import complete'});
          } else {
            window.location.assign(`/admin?${new URLSearchParams({import_export_notice: status.notice || 'Package imported successfully.'})}`);
          }
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'The package could not be imported.');
        if (!isBackgroundFieldImport && loadingCopy) loadingCopy.textContent = 'Importing directly from the uploaded package on disk. Large workspaces can take several minutes; no second upload is required.';
        window.setTimeout(() => { pollImport().catch(handleImportError); }, 1200);
      };
      const handleImportError = (error) => {
        hideLoadingOverlay();
        showInfoDialog(error instanceof Error ? error.message : 'The package could not be imported.', {title: 'Import Package Error'});
      };
      pollImport().catch(handleImportError);
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The selected file could not be inspected.', {
        title: 'Import Package Error',
      });
    }
  });
});

function selectFullEnvironmentWorkspaces() {
  const overlay = document.querySelector('[data-full-environment-workspace-overlay]');
  if (!(overlay instanceof HTMLElement)) return Promise.resolve([]);
  const checkboxes = [...overlay.querySelectorAll('.full-environment-workspace-choice input[type="checkbox"]')];
  const accept = overlay.querySelector('[data-full-environment-accept]');
  const cancel = overlay.querySelector('[data-full-environment-cancel]');
  const selectAll = overlay.querySelector('[data-full-environment-select-all]');
  const selectNone = overlay.querySelector('[data-full-environment-select-none]');
  const generatedOutputs = overlay.querySelector('[data-full-environment-generated-outputs]');
  const error = overlay.querySelector('[data-full-environment-workspace-error]');
  overlay.hidden = false;
  document.body.classList.add('loading-active');
  if (error instanceof HTMLElement) error.hidden = true;
  if (generatedOutputs instanceof HTMLInputElement) generatedOutputs.checked = true;
  return new Promise((resolve) => {
    const close = (selection) => {
      overlay.hidden = true;
      document.body.classList.remove('loading-active');
      accept?.removeEventListener('click', submit);
      cancel?.removeEventListener('click', dismiss);
      selectAll?.removeEventListener('click', checkAll);
      selectNone?.removeEventListener('click', clearAll);
      overlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      resolve(selection);
    };
    const submit = () => {
      const selected = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
      if (selected.length === 0) {
        if (error instanceof HTMLElement) error.hidden = false;
        return;
      }
      close({
        workspaceIds: selected,
        includeGeneratedOutputs: generatedOutputs instanceof HTMLInputElement ? generatedOutputs.checked : true,
      });
    };
    const dismiss = () => close(null);
    const checkAll = () => { checkboxes.forEach((checkbox) => { checkbox.checked = true; }); if (error instanceof HTMLElement) error.hidden = true; };
    const clearAll = () => { checkboxes.forEach((checkbox) => { checkbox.checked = false; }); };
    const backdrop = (event) => { if (event.target === overlay) dismiss(); };
    const keyboard = (event) => { if (event.key === 'Escape') dismiss(); };
    accept?.addEventListener('click', submit);
    cancel?.addEventListener('click', dismiss);
    selectAll?.addEventListener('click', checkAll);
    selectNone?.addEventListener('click', clearAll);
    overlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    if (accept instanceof HTMLElement) accept.focus();
  });
}

function selectTransferDestination() {
  const overlay = document.querySelector('[data-server-transfer-overlay]');
  if (!(overlay instanceof HTMLElement)) return Promise.resolve(null);
  const url = overlay.querySelector('[data-server-transfer-url]');
  const port = overlay.querySelector('[data-server-transfer-port]');
  const error = overlay.querySelector('[data-server-transfer-error]');
  const accept = overlay.querySelector('[data-server-transfer-connect]');
  const cancel = overlay.querySelector('[data-server-transfer-cancel]');
  const destinationStorageKey = 'dashboard-analytic:transfer-destination';
  try {
    const saved = JSON.parse(window.localStorage.getItem(destinationStorageKey) || 'null');
    if (url instanceof HTMLInputElement && saved?.destinationUrl) url.value = saved.destinationUrl;
    if (port instanceof HTMLInputElement && saved?.destinationPort) port.value = saved.destinationPort;
  } catch (_error) { /* Keep the defaults when browser storage is unavailable. */ }
  overlay.hidden = false;
  document.body.classList.add('loading-active');
  if (error instanceof HTMLElement) error.hidden = true;
  return new Promise((resolve) => {
    const close = (value) => {
      overlay.hidden = true;
      document.body.classList.remove('loading-active');
      accept?.removeEventListener('click', submit);
      cancel?.removeEventListener('click', dismiss);
      overlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      url?.removeEventListener('keydown', submitWithEnter);
      port?.removeEventListener('keydown', submitWithEnter);
      resolve(value);
    };
    const submit = () => {
      const destinationUrl = url instanceof HTMLInputElement ? url.value.trim() : '';
      const destinationPort = port instanceof HTMLInputElement ? port.value.trim() : '';
      if (!destinationUrl) {
        if (error instanceof HTMLElement) {
          error.textContent = 'Enter the destination server URL or IP address.';
          error.hidden = false;
        }
        url?.focus();
        return;
      }
      if (destinationPort && (Number(destinationPort) < 1 || Number(destinationPort) > 65535)) {
        if (error instanceof HTMLElement) {
          error.textContent = 'The port must be between 1 and 65535.';
          error.hidden = false;
        }
        port?.focus();
        return;
      }
      try { window.localStorage.setItem(destinationStorageKey, JSON.stringify({destinationUrl, destinationPort})); } catch (_error) { /* Ignore storage failures. */ }
      close({destinationUrl, destinationPort});
    };
    const submitWithEnter = (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      submit();
    };
    const dismiss = () => close(null);
    const backdrop = (event) => { if (event.target === overlay) dismiss(); };
    const keyboard = (event) => { if (event.key === 'Escape') dismiss(); };
    accept?.addEventListener('click', submit);
    cancel?.addEventListener('click', dismiss);
    overlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    url?.addEventListener('keydown', submitWithEnter);
    port?.addEventListener('keydown', submitWithEnter);
    url?.focus();
  });
}

document.querySelectorAll('[data-export-package-form]').forEach((form) => {
  const transferButton = form.querySelector('[data-server-transfer]');
  const selectedExportTargets = (formData) => formData.getAll('export_target').map((value) => String(value));
  const confirmGeneratedOutputs = async (formData, operation) => {
    const targets = selectedExportTargets(formData);
    if (targets.includes('full-environment')) return true;
    if (!targets.some((target) => target.startsWith('workspace:'))) {
      formData.set('include_generated_outputs', 'true');
      return true;
    }
    const result = await showConfirmDialog(
      `Include generated dashboards, reports and chart sets in this Workspace ${operation}?`,
      {
        title: `${operation} Workspace`,
        confirmLabel: operation,
        optionLabel: 'Include generated dashboards, reports and chart sets',
        optionChecked: true,
      },
    );
    if (!result.accepted) return false;
    formData.set('include_generated_outputs', String(result.optionChecked));
    return true;
  };
  transferButton?.addEventListener('click', async () => {
    if (!(form instanceof HTMLFormElement)) return;
    const formData = new FormData(form);
    if (selectedExportTargets(formData).includes('full-environment')) {
      const selection = await selectFullEnvironmentWorkspaces();
      if (selection === null) return;
      selection.workspaceIds.forEach((workspaceId) => formData.append('workspace_ids', workspaceId));
      formData.set('include_generated_outputs', String(selection.includeGeneratedOutputs));
    }
    if (!await confirmGeneratedOutputs(formData, 'Transfer')) return;
    const destination = await selectTransferDestination();
    if (!destination) return;
    formData.set('destination_url', destination.destinationUrl);
    if (destination.destinationPort) formData.set('destination_port', destination.destinationPort);
    showLoadingOverlay('Contacting destination server', 'Checking whether the destination server accepts the selected export.');
    let transferCancelUrl = '';
    let transferCancelled = false;
    if (loadingCancel instanceof HTMLButtonElement) {
      loadingCancel.hidden = false;
      loadingCancel.onclick = async () => {
        transferCancelled = true;
        loadingCancel.disabled = true;
        loadingCancel.textContent = 'Cancelling…';
        if (transferCancelUrl) {
          await fetch(transferCancelUrl, {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}}).catch(() => {});
        }
        hideLoadingOverlay();
        loadingCancel.textContent = 'Cancel operation';
      };
    }
    const handleTransferError = (error) => {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The server transfer could not be completed.', {
        title: 'Server Transfer Error',
        tone: 'error',
      });
    };
    try {
      const response = await fetch('/admin/import-export/transfers/jobs', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const responseType = response.headers.get('content-type') || '';
      if (response.redirected || !responseType.includes('application/json')) {
        throw new Error('Your session expired or the server restarted. Reload the page, log in again and retry the transfer.');
      }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.status_url) throw new Error(payload.detail || 'The transfer could not be started.');
      transferCancelUrl = payload.cancel_url || '';
      if (transferCancelled) {
        if (transferCancelUrl) await fetch(transferCancelUrl, {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}}).catch(() => {});
        return;
      }
      try { window.localStorage.setItem('dashboard-analytic:active-transfer', JSON.stringify({job_id: payload.job_id, status_url: payload.status_url})); } catch (_error) { /* Ignore storage failures. */ }
      const pollTransfer = async () => {
        const statusResponse = await fetch(payload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const transfer = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(transfer.detail || 'The transfer status could not be read.');
        if (transfer.status === 'ready') {
          try { window.localStorage.removeItem('dashboard-analytic:active-transfer'); } catch (_error) { /* Ignore storage failures. */ }
          hideLoadingOverlay();
          showInfoDialog(transfer.notice || 'The destination server received and imported the package successfully.', {
            title: 'Server Transfer Complete',
            tone: 'info',
          });
          return;
        }
        if (transfer.status === 'failed') {
          try { window.localStorage.removeItem('dashboard-analytic:active-transfer'); } catch (_error) { /* Ignore storage failures. */ }
          throw new Error(transfer.error || 'The destination server could not complete the transfer.');
        }
        if (transfer.status === 'cancelled' || transfer.status === 'cancelling') {
          try { window.localStorage.removeItem('dashboard-analytic:active-transfer'); } catch (_error) { /* Ignore storage failures. */ }
          hideLoadingOverlay();
          return;
        }
        setLoadingProgress(transfer.progress);
        const copies = {
          queued: 'Preparing the connection to the destination server.',
          connecting: 'Connecting to the destination server and creating the transfer request.',
          awaiting_acceptance: 'Waiting for a super-admin on the destination server to accept the transfer.',
          exporting: `The destination accepted the transfer. Creating the selected export package${transfer.progress ? ` — ${transfer.progress}%` : ''}.`,
          transferring: `Sending the package to the destination server${transfer.progress ? ` — ${transfer.progress}%` : ''}.`,
          remote_importing: `Package received. The destination server is ${transfer.remote_phase || 'importing it'}${transfer.progress ? ` — ${transfer.progress}%` : ''}.`,
        };
        if (loadingCopy) loadingCopy.textContent = copies[transfer.status] || 'The server transfer is in progress.';
        window.setTimeout(() => { pollTransfer().catch(handleTransferError); }, 1500);
      };
      pollTransfer().catch(handleTransferError);
    } catch (error) {
      handleTransferError(error);
    }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!(form instanceof HTMLFormElement)) return;
    const formData = new FormData(form);
    if (selectedExportTargets(formData).includes('full-environment')) {
      const selection = await selectFullEnvironmentWorkspaces();
      if (selection === null) return;
      selection.workspaceIds.forEach((workspaceId) => formData.append('workspace_ids', workspaceId));
      formData.set('include_generated_outputs', String(selection.includeGeneratedOutputs));
    }
    if (!await confirmGeneratedOutputs(formData, 'Export')) return;
    showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.job_id || !payload.status_url) {
        throw new Error(payload.detail || 'The export package could not be started.');
      }
      const pollExport = async () => {
        const statusResponse = await fetch(payload.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const status = await statusResponse.json().catch(() => ({}));
        if (!statusResponse.ok) throw new Error(status.detail || 'The export status could not be read.');
        if (status.status === 'ready' && status.download_url) {
          hideLoadingOverlay();
          const link = document.createElement('a');
          link.href = status.download_url;
          link.download = status.filename || 'dashboard-analytic-export.zip';
          document.body.appendChild(link);
          link.click();
          link.remove();
          showInfoDialog('The package is ready. Your browser download has started and can be resumed if necessary.', {
            title: 'Export Package Ready',
            tone: 'info',
          });
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'The export package could not be created.');
        setLoadingProgress(status.progress);
        if (loadingCopy) loadingCopy.textContent = status.progress > 0
          ? `Preparing the export package on the server — approximately ${status.progress}% of source data archived.`
          : 'Preparing the export package on the server. Large workspaces can take several minutes; you may keep this page open.';
        window.setTimeout(() => { pollExport().catch(handleExportError); }, 1200);
      };
      const handleExportError = (error) => {
        hideLoadingOverlay();
        showInfoDialog(error instanceof Error ? error.message : 'The export package could not be created.', {
          title: 'Export Package Error',
          tone: 'error',
        });
      };
      pollExport().catch(handleExportError);
    } catch (error) {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The export package could not be started.', {
        title: 'Export Package Error',
        tone: 'error',
      });
    }
  });
});

(() => {
  // Do not depend exclusively on a server-rendered marker: a stale outer page
  // in front of an updated Docker backend could otherwise receive offers but
  // never start the notification poll. The rendered role keeps other users
  // from making an endpoint request they are not authorised to perform.
  if (document.body.dataset.authenticatedRole !== 'super-admin') return;
  let reviewingOffer = false;
  let pollingOffers = false;
  const pollAcceptedTransfer = async (offerId) => {
    const response = await fetch(`/admin/import-export/transfers/offers/${encodeURIComponent(offerId)}`, {
      credentials: 'same-origin', headers: {Accept: 'application/json'}, cache: 'no-store',
    });
    const offer = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(offer.detail || 'The transfer status could not be read.');
    if (offer.status === 'ready') {
      hideLoadingOverlay();
      showInfoDialog(offer.notice || 'The incoming transfer was imported successfully.', {title: 'Incoming Transfer Complete', tone: 'info'});
      return;
    }
    if (offer.status === 'failed' || offer.status === 'rejected' || offer.status === 'expired' || offer.status === 'cancelled') {
      throw new Error(offer.error || 'The incoming transfer could not be completed.');
    }
    setLoadingProgress(offer.progress);
    if (loadingCopy) {
      const progress = offer.progress ? ` — ${offer.progress}%` : '';
      const copies = {
        accepted: 'Waiting for the source server to start sending the package',
        receiving: 'Receiving the package from the source server',
        received: 'Package received. Starting the import',
        importing: `Importing the received package${offer.phase ? `: ${offer.phase}` : ''}`,
      };
      loadingCopy.textContent = `${copies[offer.status] || 'Incoming transfer in progress'}${progress}.`;
    }
    window.setTimeout(() => { pollAcceptedTransfer(offerId).catch((error) => {
      hideLoadingOverlay();
      showInfoDialog(error instanceof Error ? error.message : 'The incoming transfer could not be completed.', {title: 'Incoming Transfer Error', tone: 'error'});
    }); }, 1200);
  };
  const pollIncomingTransferOffers = async () => {
    if (reviewingOffer || pollingOffers) return;
    pollingOffers = true;
    try {
      const response = await fetch('/admin/import-export/transfers/offers', {
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
        cache: 'no-store',
      });
      if (response.status === 401 || response.status === 403) {
        // A configuration swap during an import can reject one request. Keep
        // polling so a valid super-admin page recovers without being reloaded.
        return;
      }
      if (!response.ok) return;
      const payload = await response.json().catch(() => ({}));
      const offer = Array.isArray(payload.offers) ? payload.offers[0] : null;
      if (!offer) return;
      reviewingOffer = true;
      const workspaceCopy = Array.isArray(offer.workspaces) && offer.workspaces.length
        ? `\nWorkspaces: ${offer.workspaces.join(', ')}`
        : '';
      const sourceAddress = offer.source_address ? ` (${offer.source_address})` : '';
      confirmOverlay?.classList.add('incoming-transfer-confirm');
      let accepted = false;
      try {
        const importEffect = offer.kind === 'auto-calculated-fields'
          ? 'Next, choose the destination workspaces. After reception, matching field names will be updated and their applicable CDR tables will be materialized in the background.'
          : offer.kind === 'slides-templates'
            ? 'Next, choose the destination workspaces. The original workspace will be preselected when present. Matching templates will be overwritten; CDR tables will not be rebuilt.'
            : offer.kind === 'dashboards'
              ? 'Next, choose the destination workspaces. The original workspace will be preselected when present. Dashboard definitions and saved filters will be restored; generated caches are not transferred.'
            : offer.kind === 'operator-mappings'
              ? 'Next, choose the destination workspaces. Their complete Operator/Vendor aliases, order and theme colors will be replaced without modifying stored CDR values.'
          : 'After the complete package is received, it will be imported automatically and may overwrite matching configuration or workspaces.';
        accepted = await showConfirmDialog(
          `${offer.source}${sourceAddress} wants to transfer “${offer.content}” to this server.${workspaceCopy}\n\n${importEffect}`,
          {title: 'Incoming server transfer', confirmLabel: 'Accept transfer', cancelLabel: 'Reject'},
        );
      } finally {
        confirmOverlay?.classList.remove('incoming-transfer-confirm');
      }
      let destinationWorkspaceIds = [];
      if (accepted && (offer.requires_destination_workspaces || ['auto-calculated-fields', 'slides-templates', 'dashboards', 'operator-mappings'].includes(offer.kind))) {
        const matchingIds = (payload.destination_workspaces || []).filter((workspace) =>
          (offer.workspaces || []).some((name) => String(name).toLowerCase() === workspace.name.toLowerCase())
        ).map((workspace) => workspace.id);
        const selection = await selectAutoCalculatedFieldWorkspaces(payload.destination_workspaces, offer.kind, matchingIds);
        if (!selection) accepted = false;
        else destinationWorkspaceIds = selection;
      }
      const action = accepted ? 'accept' : 'reject';
      const decision = await fetch(`/admin/import-export/transfers/offers/${encodeURIComponent(offer.id)}/${action}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {Accept: 'application/json', 'Content-Type': 'application/json'},
        body: JSON.stringify({workspace_ids: destinationWorkspaceIds}),
      });
      if (!decision.ok) {
        const error = await decision.json().catch(() => ({}));
        showInfoDialog(error.detail || 'The transfer decision could not be saved.', {title: 'Incoming Transfer Error'});
      } else if (accepted) {
        if (offer.kind === 'auto-calculated-fields') {
          hideLoadingOverlay();
          showInfoDialog(
            'The transfer was accepted. Reception, import and materialization will continue in the background for the selected workspaces.',
            {title: 'Auto-calculated Fields transfer accepted'},
          );
        } else {
          showLoadingOverlay('Incoming server transfer', 'Waiting for the source server to start sending the package.');
        }
        pollAcceptedTransfer(offer.id).catch((error) => {
          hideLoadingOverlay();
          showInfoDialog(error instanceof Error ? error.message : 'The incoming transfer could not be completed.', {title: 'Incoming Transfer Error', tone: 'error'});
        });
      }
    } catch (_error) {
      // A transient polling failure should not interrupt the Admin page.
    } finally {
      reviewingOffer = false;
      pollingOffers = false;
    }
  };
  document.querySelectorAll('[data-recovered-transfer-import]').forEach((button) => {
    button.addEventListener('click', async () => {
      const offerId = button.dataset.recoveredTransferImport;
      if (!offerId) return;
      button.disabled = true;
      showLoadingOverlay('Importing recovered transfer', 'Preparing the recovered package for import.');
      try {
        const response = await fetch(`/admin/import-export/transfers/recoveries/${encodeURIComponent(offerId)}/import`, {
          method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'},
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'The recovered transfer could not be imported.');
        pollAcceptedTransfer(offerId).catch((error) => {
          hideLoadingOverlay();
          showInfoDialog(error instanceof Error ? error.message : 'The recovered transfer could not be imported.', {title: 'Recovered Transfer Error', tone: 'error'});
        });
      } catch (error) {
        hideLoadingOverlay();
        button.disabled = false;
        showInfoDialog(error instanceof Error ? error.message : 'The recovered transfer could not be imported.', {title: 'Recovered Transfer Error', tone: 'error'});
      }
    });
  });
  document.querySelectorAll('[data-recovered-transfer-delete]').forEach((button) => {
    button.addEventListener('click', async () => {
      const offerId = button.dataset.recoveredTransferDelete;
      if (!offerId) return;
      const confirmed = await showConfirmDialog('Delete this recovered transfer package permanently? It will no longer be available to import.', {
        title: 'Delete recovered package', confirmLabel: 'Delete package', tone: 'danger',
      });
      if (!confirmed) return;
      button.disabled = true;
      try {
        const response = await fetch(`/admin/import-export/transfers/recoveries/${encodeURIComponent(offerId)}/delete`, {
          method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'},
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'The recovered transfer package could not be deleted.');
        document.querySelector(`[data-recovered-transfer-row="${CSS.escape(offerId)}"]`)?.remove();
      } catch (error) {
        button.disabled = false;
        showInfoDialog(error instanceof Error ? error.message : 'The recovered transfer package could not be deleted.', {title: 'Recovered Transfer Error', tone: 'error'});
      }
    });
  });
  window.setInterval(pollIncomingTransferOffers, 3000);
  window.addEventListener('focus', pollIncomingTransferOffers);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollIncomingTransferOffers(); });
  pollIncomingTransferOffers();
})();

// The transfer itself is server-side, so a page reload should restore its
// progress dialog instead of making the user guess whether it is still running.
(() => {
  if (!document.querySelector('[data-server-transfer-listener]')) return;
  let saved;
  try { saved = JSON.parse(window.localStorage.getItem('dashboard-analytic:active-transfer') || 'null'); } catch (_error) { saved = null; }
  if (!saved?.status_url) return;
  const poll = async () => {
    const response = await fetch(saved.status_url, {credentials: 'same-origin', headers: {Accept: 'application/json'}, cache: 'no-store'});
    const transfer = await response.json().catch(() => ({}));
    if (!response.ok || transfer.status === 'failed') {
      try { window.localStorage.removeItem('dashboard-analytic:active-transfer'); } catch (_error) { /* Ignore storage failures. */ }
      if (transfer.error) showInfoDialog(transfer.error, {title: 'Server Transfer Error', tone: 'error'});
      return;
    }
    if (transfer.status === 'ready') {
      try { window.localStorage.removeItem('dashboard-analytic:active-transfer'); } catch (_error) { /* Ignore storage failures. */ }
      showInfoDialog(transfer.notice || 'The server transfer completed successfully.', {title: 'Server Transfer Complete', tone: 'info'});
      return;
    }
    showLoadingOverlay('Resuming server transfer', transfer.status === 'remote_importing' ? 'The destination server is importing the package.' : 'The server transfer is still in progress.');
    setLoadingProgress(transfer.progress);
    window.setTimeout(() => { poll().catch(() => {}); }, 1500);
  };
  poll().catch(() => {});
})();

document.querySelectorAll('form[data-loading-label]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (form.dataset.downloadForm === '1') {
      event.preventDefault();
      submitDownloadForm(form);
      return;
    }
    if (window.location.pathname === '/datasets-analysis' && form.id === 'datasets-analysis-dataset-form') {
      event.preventDefault();
      const params = buildDatasetsAnalysisParamsFromForm(form);
      if (!navigateToPersistedDatasetAnalysis(
        params.get('dataset_id'),
        params.get('input_kind'),
        form.dataset.loadingLabel,
      )) {
        showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
        replaceLocation(buildDatasetAnalysisUrl(params));
      }
      return;
    }
    if (window.location.pathname === '/datasets-analysis' && form.id === 'datasets-analysis-filters-form') {
      event.preventDefault();
      const globalCdfSelect = document.querySelector('[data-global-cdf-grouping-select]');
      const globalAggregationSelect = document.querySelector('[data-global-aggregation-select]');
      syncDatasetsAnalysisHiddenControl('cdf_grouping', globalCdfSelect?.value || 'all');
      syncDatasetsAnalysisHiddenControl('aggregation', globalAggregationSelect?.value || 'all');
      const params = buildDatasetsAnalysisParamsFromForm(form);
      params.set('load', '1');
      params.delete('cdf_overrides');
      persistDatasetsAnalysisState(params);
      persistActiveDatasetState(params);
      showLoadingOverlay(form.dataset.loadingLabel);
      window.location.search = params.toString();
      return;
    }
    showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
  });
});

function showConfirmDialog(message, options = {}) {
  if (!confirmOverlay || !confirmTitle || !confirmCopy || !confirmAccept || !confirmCancel) {
    const accepted = window.confirm(message || 'Are you sure?');
    if (options.secondaryLabel || options.tertiaryLabel) {
      if (accepted) return Promise.resolve('confirm');
      if (options.secondaryLabel && window.confirm(`${options.secondaryLabel} instead?`)) return Promise.resolve('secondary');
      return Promise.resolve(options.tertiaryLabel && window.confirm(`${options.tertiaryLabel} instead?`) ? 'tertiary' : null);
    }
    return Promise.resolve(options.optionLabel ? {accepted, optionChecked: Boolean(options.optionChecked)} : accepted);
  }

  confirmTitle.textContent = options.title || 'Confirm action';
  if (options.copyHtml) confirmCopy.innerHTML = options.copyHtml;
  else confirmCopy.textContent = message || options.copy || 'Are you sure you want to continue?';
  confirmAccept.textContent = options.confirmLabel || 'Confirm';
  confirmCancel.textContent = options.cancelLabel || 'Cancel';
  confirmCancel.hidden = options.hideCancel === true;
  const hasSecondary = Boolean(options.secondaryLabel && confirmSecondary);
  const hasTertiary = Boolean(options.tertiaryLabel && confirmTertiary);
  const hasAlternatives = hasSecondary || hasTertiary;
  confirmOverlay.classList.toggle('confirm-wide-actions', hasAlternatives && options.wideActions === true);
  confirmOverlay.classList.toggle('confirm-four-actions', hasTertiary);
  if (confirmSecondary) {
    confirmSecondary.textContent = options.secondaryLabel || 'Alternative';
    confirmSecondary.hidden = !hasSecondary;
  }
  if (confirmTertiary) {
    confirmTertiary.textContent = options.tertiaryLabel || 'Alternative';
    confirmTertiary.hidden = !hasTertiary;
  }
  const hasOption = Boolean(options.optionLabel && confirmOption && confirmOptionInput && confirmOptionLabel);
  if (hasOption) {
    confirmOptionLabel.textContent = options.optionLabel;
    confirmOptionLabel.title = options.optionTitle || '';
    confirmOptionInput.checked = Boolean(options.optionChecked);
    confirmOption.hidden = false;
  }
  confirmOverlay.hidden = false;
  document.body.classList.add('loading-active');

  return new Promise((resolve) => {
    const close = (accepted) => {
      confirmOverlay.hidden = true;
      document.body.classList.remove('loading-active');
      confirmAccept.removeEventListener('click', handleAccept);
      confirmCancel.removeEventListener('click', handleCancel);
      confirmSecondary?.removeEventListener('click', handleSecondary);
      confirmTertiary?.removeEventListener('click', handleTertiary);
      confirmOverlay.removeEventListener('click', handleBackdrop);
      window.removeEventListener('keydown', handleKeydown);
      confirmCancel.hidden = false;
      confirmCancel.textContent = 'Cancel';
      confirmOverlay.classList.remove('confirm-wide-actions');
      confirmOverlay.classList.remove('confirm-four-actions');
      if (confirmSecondary) {
        confirmSecondary.hidden = true;
        confirmSecondary.textContent = 'Alternative';
      }
      if (confirmTertiary) {
        confirmTertiary.hidden = true;
        confirmTertiary.textContent = 'Alternative';
      }
      const optionChecked = hasOption && Boolean(confirmOptionInput?.checked);
      if (confirmOption) confirmOption.hidden = true;
      if (confirmOptionInput) confirmOptionInput.checked = false;
      if (confirmOptionLabel) confirmOptionLabel.title = '';
      resolve(hasAlternatives ? accepted : (hasOption ? {accepted, optionChecked} : accepted));
    };

    const handleAccept = () => close(hasAlternatives ? 'confirm' : true);
    const handleSecondary = () => close('secondary');
    const handleTertiary = () => close('tertiary');
    const handleCancel = () => close(hasAlternatives ? null : false);
    const handleBackdrop = (event) => {
      if (event.target === confirmOverlay) {
        close(hasAlternatives ? null : false);
      }
    };
    const handleKeydown = (event) => {
      if (event.key === 'Escape') {
        close(hasAlternatives ? null : false);
      }
    };

    confirmAccept.addEventListener('click', handleAccept);
    confirmCancel.addEventListener('click', handleCancel);
    confirmSecondary?.addEventListener('click', handleSecondary);
    confirmTertiary?.addEventListener('click', handleTertiary);
    confirmOverlay.addEventListener('click', handleBackdrop);
    window.addEventListener('keydown', handleKeydown);
    confirmAccept.focus();
  });
}

document.querySelectorAll('form[action="/workspace/calculated-dimensions/import"]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    if (form.dataset.confirmed === '1') {
      delete form.dataset.confirmed;
      return;
    }
    event.preventDefault();
    const fileInput = form.querySelector('input[name="dimensions_file"]');
    const file = fileInput instanceof HTMLInputElement ? fileInput.files?.[0] : null;
    if (!file) return;

    let imported;
    try {
      imported = JSON.parse(await file.text());
      if (!Array.isArray(imported)) throw new Error('The selected JSON must contain an array of auto-calculated fields.');
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'The selected JSON could not be read.', {
        title: 'Auto-calculated Fields import', tone: 'error',
      });
      return;
    }

    const panel = form.closest('[data-workspace-calculated-dimensions-panel]');
    let current = [];
    try { current = JSON.parse(panel?.dataset.calculatedDimensions || '[]'); } catch (_error) { current = []; }
    const currentNames = new Set(current.map((item) => String(item?.name || '').trim().toLocaleLowerCase()).filter(Boolean));
    const overwritten = [...new Set(imported
      .map((item) => String(item?.name || '').trim())
      .filter((name) => name && currentNames.has(name.toLocaleLowerCase())))];
    const fieldCount = imported.length;
    const message = overwritten.length
      ? `This file contains ${fieldCount} auto-calculated field${fieldCount === 1 ? '' : 's'}. ${overwritten.length} already exist${overwritten.length === 1 ? 's' : ''} in this workspace and will be overwritten: ${overwritten.join(', ')}. Applicable CDR tables will then be updated in the background. Continue?`
      : `This will import ${fieldCount} auto-calculated field${fieldCount === 1 ? '' : 's'} into this workspace. Applicable CDR tables will then be updated in the background. Continue?`;
    const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[character]));
    const copyHtml = overwritten.length
      ? `This file contains ${fieldCount} auto-calculated field${fieldCount === 1 ? '' : 's'}.<br><strong>${overwritten.length} existing field${overwritten.length === 1 ? '' : 's'} will be overwritten:</strong><br>${overwritten.map((name) => `<strong>• ${escapeHtml(name)}</strong>`).join('<br>')}<br><br>Applicable CDR tables will then be updated in the background. Continue?`
      : null;
    const accepted = await showConfirmDialog(message, {
      title: overwritten.length ? 'Overwrite Auto-calculated Fields?' : 'Import Auto-calculated Fields',
      confirmLabel: overwritten.length ? 'Overwrite and Import' : 'Import',
      tone: overwritten.length ? 'warning' : 'info',
      copyHtml,
    });
    if (!accepted) return;
    form.dataset.confirmed = '1';
    const submit = form.querySelector('button[type="submit"]');
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    HTMLFormElement.prototype.submit.call(form);
  });
});

function showCatalogueInsertChoice(slide) {
  if (!catalogueInsertOverlay || !catalogueInsertTitle || !catalogueInsertCopy || !catalogueInsertChart || !catalogueInsertSlide || !catalogueInsertCancel) {
    const response = window.prompt(`Slide ${slide}: type chart to add a chart, or slide to add a new slide.`, 'chart');
    return Promise.resolve(response?.trim().toLocaleLowerCase() === 'slide' ? 'slide' : response?.trim().toLocaleLowerCase() === 'chart' ? 'chart' : null);
  }
  catalogueInsertTitle.textContent = `Add after slide ${slide}`;
  catalogueInsertCopy.textContent = 'Add another chart to this slide, or insert a new blank slide after it. A new slide renumbers the following slides.';
  catalogueInsertOverlay.hidden = false;
  document.body.classList.add('loading-active');
  return new Promise((resolve) => {
    const close = (choice) => {
      catalogueInsertOverlay.hidden = true;
      document.body.classList.remove('loading-active');
      catalogueInsertChart.removeEventListener('click', addChart);
      catalogueInsertSlide.removeEventListener('click', addSlide);
      catalogueInsertCancel.removeEventListener('click', cancel);
      catalogueInsertOverlay.removeEventListener('click', backdrop);
      window.removeEventListener('keydown', keyboard);
      resolve(choice);
    };
    const addChart = () => close('chart');
    const addSlide = () => close('slide');
    const cancel = () => close(null);
    const backdrop = (event) => { if (event.target === catalogueInsertOverlay) cancel(); };
    const keyboard = (event) => { if (event.key === 'Escape') cancel(); };
    catalogueInsertChart.addEventListener('click', addChart);
    catalogueInsertSlide.addEventListener('click', addSlide);
    catalogueInsertCancel.addEventListener('click', cancel);
    catalogueInsertOverlay.addEventListener('click', backdrop);
    window.addEventListener('keydown', keyboard);
    catalogueInsertChart.focus();
  });
}

function showInfoDialog(message, options = {}) {
  if (!infoOverlay || !infoTitle || !infoCopy || !infoClose) {
    window.alert(message || 'Update complete');
    options.onClose?.();
    return;
  }
  const tone = ['info', 'warning', 'error'].includes(options.tone) ? options.tone : 'info';
  const toneLabels = {info: 'Information', warning: 'Warning', error: 'Error'};
  const toneIcons = {info: 'i', warning: '!', error: '×'};
  infoOverlay.dataset.tone = tone;
  if (infoEyebrow) infoEyebrow.textContent = toneLabels[tone];
  if (infoIcon) infoIcon.textContent = toneIcons[tone];
  infoTitle.textContent = options.title || toneLabels[tone];
  infoCopy.textContent = message || '';
  infoOverlay.hidden = false;
  document.body.classList.add('loading-active');
  const close = () => {
    infoOverlay.hidden = true;
    delete infoOverlay.dataset.tone;
    document.body.classList.remove('loading-active');
    infoClose.removeEventListener('click', close);
    infoOverlay.removeEventListener('click', handleBackdrop);
    window.removeEventListener('keydown', handleKeydown);
    options.onClose?.();
  };
  const handleBackdrop = (event) => { if (event.target === infoOverlay) close(); };
  const handleKeydown = (event) => { if (event.key === 'Escape') close(); };
  infoClose.addEventListener('click', close);
  infoOverlay.addEventListener('click', handleBackdrop);
  window.addEventListener('keydown', handleKeydown);
  infoClose.focus();
}

(() => {
  const openButton = document.querySelector('[data-change-password-open]');
  const overlay = document.getElementById('change-password-overlay');
  const form = document.querySelector('[data-change-password-form]');
  const cancel = document.querySelector('[data-change-password-cancel]');
  const error = document.querySelector('[data-change-password-error]');
  if (!openButton || !overlay || !form || !cancel) return;
  const close = () => { overlay.hidden = true; form.reset(); if (error) error.hidden = true; };
  const open = () => { overlay.hidden = false; form.querySelector('input')?.focus(); };
  openButton.addEventListener('click', open);
  openButton.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
  cancel.addEventListener('click', close);
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (error) error.hidden = true;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const response = await fetch('/account/change-password', {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'The password could not be changed.');
      close();
      showInfoDialog('Your password has been changed successfully.', {title: 'Password changed', tone: 'info'});
    } catch (requestError) {
      if (error) { error.textContent = requestError.message; error.hidden = false; }
    } finally {
      if (submit) submit.disabled = false;
    }
  });
})();

function clearCatalogueImportQuery() {
  const url = new URL(window.location.href);
  url.searchParams.delete('catalogue_notice');
  url.searchParams.delete('catalogue_error');
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

const catalogueImportError = document.querySelector('[data-catalogue-import-error]');
if (catalogueImportError?.textContent.trim()) {
  requestAnimationFrame(() => {
    showInfoDialog(catalogueImportError.textContent.trim(), {
      title: 'Report Templates Import Failed',
      onClose: clearCatalogueImportQuery,
    });
  });
}

const catalogueImportNotice = document.querySelector('[data-catalogue-import-notice]');
if (catalogueImportNotice?.textContent.trim()) {
  requestAnimationFrame(() => {
    showInfoDialog(catalogueImportNotice.textContent.trim(), {
      title: 'Report Templates Imported',
      onClose: clearCatalogueImportQuery,
    });
  });
}

function bindConfirmForm(form) {
  if (form.dataset.confirmBound === '1') return;
  form.dataset.confirmBound = '1';
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const accepted = await showConfirmDialog(form.dataset.confirm, {
      title: form.dataset.confirmTitle || 'Confirm action',
      confirmLabel: form.dataset.confirmLabel || 'Confirm',
    });
    if (accepted) {
      const parentDialog = form.closest('dialog');
      if (parentDialog?.open) {
        parentDialog.close();
      }
      if (form.dataset.confirmLoadingLabel) {
        showLoadingOverlay(form.dataset.confirmLoadingLabel, form.dataset.confirmLoadingCopy);
      }
      if (form.action.includes('/admin/report-templates/')) {
        preserveAdminScrollPosition();
      }
      if (isChartMappingForm(form)) await submitChartMappingForm(form);
      else form.submit();
    }
  });
}

document.querySelectorAll('form[data-confirm]').forEach(bindConfirmForm);

function isChartMappingForm(form) {
  try {
    return /^\/admin\/(?:operator|vendor)-mappings\/(?:save|delete|move)$/.test(new URL(form.action, window.location.href).pathname);
  } catch (_error) {
    return false;
  }
}

async function submitChartMappingForm(form) {
  if (!(form instanceof HTMLFormElement) || form.dataset.mappingSubmitting === '1') return;
  const panel = form.closest('[data-panel-state-key^="admin:"]');
  const panelKey = panel?.dataset.panelStateKey;
  if (!panelKey || !['admin:operator-mappings', 'admin:vendor-mappings'].includes(panelKey)) return;
  form.dataset.mappingSubmitting = '1';
  const scrollTop = window.scrollY;
  const scrollLeft = window.scrollX;
  const submitters = panel.querySelectorAll('button[type="submit"]');
  submitters.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(form.action, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    if (!response.ok) throw new Error(`The mapping could not be updated (status ${response.status}).`);
    const freshDocument = new DOMParser().parseFromString(await response.text(), 'text/html');
    const selector = `[data-panel-state-key="${panelKey}"] .collapsible-panel-body`;
    const currentBody = document.querySelector(selector);
    const freshBody = freshDocument.querySelector(selector);
    if (!(currentBody instanceof HTMLElement) || !(freshBody instanceof HTMLElement)) {
      throw new Error('The updated mapping table could not be loaded.');
    }
    currentBody.replaceWith(freshBody);
    bindChartMappingForms(freshBody);
    freshBody.querySelectorAll('form[data-confirm]').forEach(bindConfirmForm);
    window.requestAnimationFrame(() => window.scrollTo({
      top: scrollTop, left: scrollLeft, behavior: 'auto',
    }));
  } catch (error) {
    submitters.forEach((button) => { button.disabled = false; });
    showInfoDialog(error instanceof Error ? error.message : 'The mapping could not be updated.', {
      title: 'Mapping Update Failed', tone: 'error',
    });
  } finally {
    form.dataset.mappingSubmitting = '0';
  }
}

function bindChartMappingForms(root = document) {
  root.querySelectorAll('form').forEach((form) => {
    if (!isChartMappingForm(form) || form.dataset.confirm || form.dataset.mappingBound === '1') return;
    form.dataset.mappingBound = '1';
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      submitChartMappingForm(form);
    });
  });
}

bindChartMappingForms();

function sizeAdminDatasetNameColumn(panel = document) {
  const table = panel.querySelector?.('.admin-datasets-table');
  const nameColumn = table?.querySelector('[data-admin-dataset-name-column]');
  const inputs = table?.querySelectorAll('[data-admin-dataset-name-input]');
  if (!table || !nameColumn || !inputs?.length) return;

  const probe = document.createElement('span');
  const sample = inputs[0];
  const styles = window.getComputedStyle(sample);
  probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${styles.font};letter-spacing:${styles.letterSpacing};`;
  document.body.appendChild(probe);
  const longest = Math.max(...Array.from(inputs, (input) => {
    probe.textContent = input.value;
    return probe.getBoundingClientRect().width;
  }));
  probe.remove();
  nameColumn.style.width = `${Math.ceil(longest + 82)}px`;
}

function bindAdminDatasetRenameForm(form) {
  if (form.dataset.renameBound === '1') return;
  form.dataset.renameBound = '1';
  const input = form.querySelector('[data-admin-dataset-name-input]');
  const save = form.querySelector('[data-admin-dataset-rename-save]');
  if (!(input instanceof HTMLInputElement) || !(save instanceof HTMLButtonElement)) return;
  let savedName = input.value;

  input.addEventListener('focus', () => { save.hidden = false; });
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      if (document.activeElement === input) return;
      input.value = savedName;
      save.hidden = true;
    }, 120);
  });
  // Keep focus on the field while the button is pressed so blur does not hide
  // the confirmation control before its form submission is dispatched.
  save.addEventListener('mousedown', (event) => event.preventDefault());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showLoadingOverlay(
      form.dataset.loadingLabel || 'Renaming dataset',
      form.dataset.loadingCopy || 'Please wait while the dataset file, path and materialised references are updated.',
    );
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin',
        headers: {Accept: 'application/json'},
      });
      const content = await response.text();
      if (!response.ok) {
        let message = `The dataset could not be renamed (status ${response.status}).`;
        try { message = JSON.parse(content).detail || message; } catch (_error) { /* Use fallback message. */ }
        throw new Error(message);
      }
      const payload = JSON.parse(content);
      savedName = String(payload.file_name || input.value);
      input.value = savedName;
      input.setAttribute('size', String(savedName.length));
      save.hidden = true;
      const row = form.closest('tr');
      const pathCell = row?.querySelector('td[data-label="Path"]');
      if (pathCell) pathCell.textContent = String(payload.stored_path || '');
      row?.querySelectorAll('[data-dataset-name]').forEach((control) => {
        control.dataset.datasetName = savedName;
      });
      window.requestAnimationFrame(() => sizeAdminDatasetNameColumn(form.closest('[data-panel-state-key="admin:datasets"]')));
    } catch (error) {
      showInfoDialog(error instanceof Error ? error.message : 'The dataset could not be renamed.', {
        title: 'Dataset Rename Failed', tone: 'error',
      });
    } finally {
      hideLoadingOverlay();
    }
  });
}

document.querySelectorAll('[data-admin-dataset-rename-form]').forEach(bindAdminDatasetRenameForm);

function remapAdminDatasetControls(idMapping) {
  if (!idMapping || typeof idMapping !== 'object') return;
  const controls = document.querySelectorAll([
    '[data-admin-vendor-mapping-choice]',
    '[data-admin-vendor-clearing-choice]',
    '[data-admin-reprocess-dataset-choice]',
    '[data-admin-vendor-mapping-dialog] option[value]',
  ].join(', '));
  controls.forEach((control) => {
    const replacement = idMapping[String(control.value)];
    if (replacement !== undefined) control.value = String(replacement);
  });
}

function refreshAdminIndividualDatasetOptions(freshDocument) {
  const currentSelect = document.querySelector('[data-database-table-select]');
  const freshSelect = freshDocument.querySelector('[data-database-table-select]');
  if (!(currentSelect instanceof HTMLSelectElement) || !(freshSelect instanceof HTMLSelectElement)) return;
  const currentGroup = Array.from(currentSelect.querySelectorAll('optgroup'))
    .find((group) => group.label === 'Individual Datasets');
  const freshGroup = Array.from(freshSelect.querySelectorAll('optgroup'))
    .find((group) => group.label === 'Individual Datasets');
  if (!currentGroup || !freshGroup) return;
  const selectedValue = currentSelect.value;
  currentGroup.replaceWith(freshGroup);
  if (Array.from(currentSelect.options).some((option) => option.value === selectedValue)) {
    currentSelect.value = selectedValue;
  }
}

document.addEventListener('submit', async (event) => {
  const form = event.target instanceof HTMLFormElement
    ? event.target.closest('[data-admin-dataset-move-form]')
    : null;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault();
  if (form.dataset.moveSubmitting === '1') return;
  form.dataset.moveSubmitting = '1';
  const scrollTop = window.scrollY;
  const scrollLeft = window.scrollX;
  showLoadingOverlay(form.dataset.loadingLabel, form.dataset.loadingCopy);
  try {
    const response = await fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      credentials: 'same-origin',
      headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    });
    const content = await response.text();
    let payload = {};
    try { payload = content ? JSON.parse(content) : {}; } catch (_error) { /* Use the request fallback below. */ }
    if (!response.ok) {
      throw new Error(payload.detail || `The dataset order could not be updated (status ${response.status}).`);
    }

    const pageResponse = await fetch('/admin', {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'X-Requested-With': 'XMLHttpRequest'},
    });
    if (!pageResponse.ok) throw new Error('The updated Dataset Management table could not be loaded.');
    const freshDocument = new DOMParser().parseFromString(await pageResponse.text(), 'text/html');
    const currentTable = document.querySelector('.admin-datasets-table');
    const freshTable = freshDocument.querySelector('.admin-datasets-table');
    if (!(currentTable instanceof HTMLTableElement) || !(freshTable instanceof HTMLTableElement)) {
      throw new Error('The updated Dataset Management table could not be found.');
    }

    const existingPager = currentTable.closest('.table-wrap')?.nextElementSibling;
    if (existingPager?.classList.contains('mobile-card-pagination')) existingPager.remove();
    currentTable.replaceWith(freshTable);
    remapAdminDatasetControls(payload.id_mapping);
    refreshAdminIndividualDatasetOptions(freshDocument);
    freshTable.querySelectorAll('[data-admin-dataset-rename-form]').forEach(bindAdminDatasetRenameForm);
    freshTable.querySelectorAll('form[data-confirm]').forEach(bindConfirmForm);
    window.requestAnimationFrame(() => {
      sizeAdminDatasetNameColumn(freshTable.closest('[data-panel-state-key="admin:datasets"]'));
      window.scrollTo({top: scrollTop, left: scrollLeft, behavior: 'auto'});
    });
  } catch (error) {
    showInfoDialog(error instanceof Error ? error.message : 'The dataset order could not be updated.', {
      title: 'Dataset Reordering Failed', tone: 'error',
    });
  } finally {
    form.dataset.moveSubmitting = '0';
    hideLoadingOverlay();
  }
});

function setupAdminDatasetChangeDraft() {
  const table = document.querySelector('.admin-datasets-table');
  const body = table?.querySelector('[data-admin-dataset-draft-body]');
  const apply = document.querySelector('[data-admin-dataset-apply-changes]');
  if (!(table instanceof HTMLTableElement) || !(body instanceof HTMLTableSectionElement) || !(apply instanceof HTMLButtonElement)) return;

  const originalOrder = Array.from(body.querySelectorAll('tr[data-admin-dataset-id]'), (row) => String(row.dataset.adminDatasetId));
  const reorderingBlocked = table.dataset.adminDatasetReorderingBlocked === '1';
  let submitting = false;
  const rows = () => Array.from(body.querySelectorAll('tr[data-admin-dataset-id]'));
  const draft = () => {
    const order = rows().map((row) => String(row.dataset.adminDatasetId));
    const names = {};
    body.querySelectorAll('[data-admin-dataset-name-input]').forEach((input) => {
      if (!(input instanceof HTMLInputElement)) return;
      const row = input.closest('tr[data-admin-dataset-id]');
      const original = String(input.dataset.adminDatasetOriginalName || '');
      if (row?.dataset.adminDatasetId && input.value !== original) names[row.dataset.adminDatasetId] = input.value;
    });
    return {order, names};
  };
  const sync = () => {
    const current = draft();
    const changed = current.order.some((id, index) => id !== originalOrder[index]) || Object.keys(current.names).length > 0;
    apply.disabled = submitting || !changed;
    rows().forEach((row, index, collection) => {
      row.querySelectorAll('[data-admin-dataset-move]').forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) return;
        button.disabled = reorderingBlocked
          || (button.dataset.adminDatasetMove === 'up' && index === 0)
          || (button.dataset.adminDatasetMove === 'down' && index === collection.length - 1);
      });
    });
    sizeAdminDatasetNameColumn(table.closest('[data-panel-state-key="admin:datasets"]'));
  };
  body.addEventListener('click', (event) => {
    const button = event.target instanceof Element ? event.target.closest('[data-admin-dataset-move]') : null;
    if (!(button instanceof HTMLButtonElement) || button.disabled || submitting) return;
    const row = button.closest('tr[data-admin-dataset-id]');
    if (!row) return;
    if (button.dataset.adminDatasetMove === 'up' && row.previousElementSibling) body.insertBefore(row, row.previousElementSibling);
    if (button.dataset.adminDatasetMove === 'down' && row.nextElementSibling) body.insertBefore(row.nextElementSibling, row);
    sync();
  });
  body.addEventListener('input', (event) => {
    if (event.target instanceof HTMLInputElement && event.target.matches('[data-admin-dataset-name-input]')) sync();
  });
  apply.addEventListener('click', async () => {
    const changes = draft();
    if (apply.disabled || submitting) return;
    submitting = true;
    sync();
    try {
      const response = await fetch('/admin/datasets/apply-changes', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        body: JSON.stringify(changes),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'The dataset changes could not be queued.');
      apply.textContent = 'Changes queued';
      showInfoDialog('Dataset changes are being applied in the background. You can follow progress or stop the task from the floating task panel.', {
        title: 'Dataset changes queued', tone: 'success',
      });
    } catch (error) {
      submitting = false;
      sync();
      showInfoDialog(error instanceof Error ? error.message : 'The dataset changes could not be queued.', {
        title: 'Dataset changes failed', tone: 'error',
      });
    }
  });
  sync();
}

setupAdminDatasetChangeDraft();

document.querySelectorAll('[data-file-picker-input]').forEach((filePickerInput) => {
  const filePickerText = filePickerInput.closest('.file-picker-shell')?.querySelector('[data-file-picker-text]');
  if (!(filePickerInput instanceof HTMLInputElement) || !(filePickerText instanceof HTMLElement)) return;
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
});

if (inputKindSelect && datasetSelect) {
  const persistControlValue = (control, value) => {
    try {
      window.localStorage.setItem(buildPersistenceKey(control), JSON.stringify(value));
    } catch (_error) {
      // Ignore storage failures.
    }
  };

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

  const persistActiveDatasetContext = () => {
    const params = new URLSearchParams(window.location.search);
    const currentDatasetId = params.get('dataset_id') || datasetSelect.value;
    if (!currentDatasetId) return;

    const matchingOption = Array.from(datasetSelect.options).find((option) => String(option.value) === String(currentDatasetId));
    if (!matchingOption) return;

    persistControlValue(datasetSelect, String(currentDatasetId));
    const datasetKind = String(matchingOption.dataset.datasetKind || '');
    if (datasetKind) {
      persistControlValue(inputKindSelect, datasetKind);
    }
    const datasetParams = new URLSearchParams();
    datasetParams.set('dataset_id', String(currentDatasetId));
    if (datasetKind) {
      datasetParams.set('input_kind', datasetKind);
    }
    persistActiveDatasetState(datasetParams);
  };

  const maybeRestoreLastDataset = () => {
    if (window.location.pathname !== '/datasets-analysis' || hasPendingLocationRestore) return;
    const params = new URLSearchParams(window.location.search);
    if (params.has('dataset_id')) {
      persistActiveDatasetContext();
      return;
    }
    const persistedDatasetId = window.localStorage.getItem(buildPersistenceKey(datasetSelect));
    if (!persistedDatasetId) return;

    let restoredValue;
    try {
      restoredValue = JSON.parse(persistedDatasetId);
    } catch (_error) {
      return;
    }
    if (!restoredValue) return;

    const matchingOption = Array.from(datasetSelect.options).find((option) => String(option.value) === String(restoredValue));
    if (!matchingOption) return;

    params.set('dataset_id', String(restoredValue));
    const matchingKind = String(matchingOption.dataset.datasetKind || '');
    if (matchingKind) {
      params.set('input_kind', matchingKind);
    } else if (inputKindSelect.value) {
      params.set('input_kind', String(inputKindSelect.value));
    }
    replaceLocation(`/datasets-analysis?${params.toString()}`);
  };

  persistActiveDatasetContext();
  maybeRestoreLastDataset();
}

if (logTypeFilter) {
  const syncLogRows = () => {
    const selectedType = String(logTypeFilter.value || 'Error');
    document.querySelectorAll('[data-log-row]').forEach((row) => {
      const rowType = String(row.getAttribute('data-log-type') || 'Info');
      row.hidden = selectedType !== 'all' && rowType !== selectedType;
    });
  };

  logTypeFilter.addEventListener('change', syncLogRows);
  syncLogRows();
}

const appLogsPanel = document.querySelector('[data-app-logs-panel]');
if (appLogsPanel) {
  const appLogFiltersStorageKey = 'dashboard-analytic:/app-logs:filters';
  const userFilter = appLogsPanel.querySelector('[data-app-log-user-filter]');
  const executorFilter = appLogsPanel.querySelector('[data-app-log-executor-filter]');
  const dateFilter = appLogsPanel.querySelector('[data-app-log-date-filter]');
  const typeFilter = appLogsPanel.querySelector('[data-app-log-type-filter]');
  const actionFilter = appLogsPanel.querySelector('[data-app-log-action-filter]');
  const clearFilters = appLogsPanel.querySelector('[data-app-log-clear-filters]');
  const noResults = appLogsPanel.querySelector('[data-app-log-no-results]');
  const body = appLogsPanel.querySelector('[data-app-log-body]');
  const count = appLogsPanel.querySelector('[data-app-log-count]');
  const refreshButton = appLogsPanel.querySelector('[data-app-log-refresh]');
  const executionLogOutput = document.querySelector('[data-execution-log-output]');
  const executionLogCount = document.querySelector('[data-execution-log-count]');
  let rows = Array.from(appLogsPanel.querySelectorAll('[data-app-log-row]'));
  let refreshInProgress = false;
  let appLogsSnapshot = '';
  let executionStreamConnected = false;
  const restorePagePosition = (position) => {
    window.requestAnimationFrame(() => window.scrollTo(window.scrollX, position));
  };
  const renderExecutionLogs = (entries) => {
    if (!executionLogOutput) return;
    const executionLogs = Array.isArray(entries) ? entries : [];
    const nextOutput = executionLogs.length
      ? executionLogs.join('\n')
      : 'No server log entries captured yet. Restart the application once to begin capturing its execution log.';
    if (executionLogOutput.textContent === nextOutput) return;
    const pagePosition = window.scrollY;
    const scrollPosition = executionLogOutput.scrollTop;
    const wasAtBottom = scrollPosition + executionLogOutput.clientHeight >= executionLogOutput.scrollHeight - 4;
    executionLogOutput.textContent = nextOutput;
    executionLogOutput.scrollTop = wasAtBottom ? executionLogOutput.scrollHeight : scrollPosition;
    if (executionLogCount) executionLogCount.textContent = `${executionLogs.length} entries`;
    restorePagePosition(pagePosition);
  };
  const restoreSelectValue = (control, value) => {
    if (!control || !value) return;
    if (Array.from(control.options).some((option) => option.value === value)) control.value = value;
  };
  try {
    const savedFilters = JSON.parse(window.localStorage.getItem(appLogFiltersStorageKey) || '{}');
    restoreSelectValue(userFilter, savedFilters.user);
    restoreSelectValue(executorFilter, savedFilters.executor);
    restoreSelectValue(dateFilter, savedFilters.date);
    restoreSelectValue(typeFilter, savedFilters.type);
    restoreSelectValue(actionFilter, savedFilters.action);
  } catch (_error) {
    // The log view remains fully usable when browser storage is unavailable.
  }
  const persistAppLogFilters = () => {
    try {
      window.localStorage.setItem(appLogFiltersStorageKey, JSON.stringify({
        user: userFilter?.value || 'all', date: dateFilter?.value || 'all',
        executor: executorFilter?.value || 'all',
        type: typeFilter?.value || 'all', action: actionFilter?.value || 'all',
      }));
    } catch (_error) {
      // Persistence is a convenience and must not block filtering.
    }
  };
  const syncAppLogRows = ({resetMobilePage = false} = {}) => {
    let visibleCount = 0;
    rows.forEach((row) => {
      const matches = (
        (!userFilter || userFilter.value === 'all' || String(row.dataset.appLogUser || '').toLocaleLowerCase() === String(userFilter.value || '').toLocaleLowerCase())
        && (!executorFilter || executorFilter.value === 'all' || String(row.dataset.appLogExecutor || '').toLocaleLowerCase() === String(executorFilter.value || '').toLocaleLowerCase())
        && (!dateFilter || dateFilter.value === 'all' || row.dataset.appLogDate === dateFilter.value)
        && (!typeFilter || typeFilter.value === 'all' || row.dataset.appLogType === typeFilter.value)
        && (!actionFilter || actionFilter.value === 'all' || row.dataset.appLogAction === actionFilter.value)
      );
      row.hidden = !matches;
      // Card-table rules use grid display on compact phones. Keep an explicit
      // inline display state too, so a filtered-out App Log can never remain
      // visible because of a card presentation rule.
      row.style.display = matches ? '' : 'none';
      if (matches) visibleCount += 1;
    });
    if (noResults) noResults.hidden = visibleCount > 0 || rows.length === 0;
    // New filters should start at their first matching entry.  A manual or
    // background refresh retains the current card, unless that page no
    // longer exists after the refreshed rows are applied.
    body?.dispatchEvent(new CustomEvent('mobile-card-pagination:refresh', {
      bubbles: true, detail: {reset: resetMobilePage},
    }));
    refreshFilterOptionsFromTableRows();
  };
  const replaceSelectOptions = (control, values, allLabel, optionLabel = (value) => value) => {
    if (!control) return;
    const selected = control.value || 'all';
    control.replaceChildren(new Option(allLabel, 'all'), ...values.map((value) => new Option(optionLabel(value), value)));
    control.value = Array.from(control.options).some((option) => option.value === selected) ? selected : 'all';
  };
  const refreshFilterOptionsFromTableRows = () => {
    // Compact-phone pagination keeps non-current cards in the DOM. They are
    // still rows of this table. Each selector is a facet: its values come
    // from every loaded row that matches the other active filters, never just
    // the current card page.
    const tableRows = rows;
    const rowMatchesOtherFilters = (row, excludedFilter) => (
      (excludedFilter === 'user' || !userFilter || userFilter.value === 'all' || String(row.dataset.appLogUser || '').toLocaleLowerCase() === String(userFilter.value || '').toLocaleLowerCase())
      && (excludedFilter === 'executor' || !executorFilter || executorFilter.value === 'all' || String(row.dataset.appLogExecutor || '').toLocaleLowerCase() === String(executorFilter.value || '').toLocaleLowerCase())
      && (excludedFilter === 'date' || !dateFilter || dateFilter.value === 'all' || row.dataset.appLogDate === dateFilter.value)
      && (excludedFilter === 'type' || !typeFilter || typeFilter.value === 'all' || row.dataset.appLogType === typeFilter.value)
      && (excludedFilter === 'action' || !actionFilter || actionFilter.value === 'all' || row.dataset.appLogAction === actionFilter.value)
    );
    const valuesFor = (name, excludedFilter, normalise = (value) => value) => [...new Set(
      tableRows.filter((row) => rowMatchesOtherFilters(row, excludedFilter))
        .map((row) => normalise(String(row.dataset[name] || ''))).filter(Boolean),
    )].sort();
    replaceSelectOptions(userFilter, valuesFor('appLogUser', 'user', (value) => value.toLocaleLowerCase()), 'All users');
    replaceSelectOptions(executorFilter, valuesFor('appLogExecutor', 'executor', (value) => value.toLocaleLowerCase()), 'All executors');
    replaceSelectOptions(dateFilter, valuesFor('appLogDate', 'date').reverse(), 'All dates');
    replaceSelectOptions(typeFilter, valuesFor('appLogType', 'type'), 'All events', (value) => `${value} only`);
    replaceSelectOptions(actionFilter, valuesFor('appLogAction', 'action'), 'All actions');
  };
  const createAppLogRow = (log) => {
    const row = document.createElement('tr');
    row.dataset.appLogRow = '';
    row.dataset.appLogUser = String(log.username || '').toLocaleLowerCase();
    row.dataset.appLogExecutor = String(log.executed_by || '—').toLocaleLowerCase();
    row.dataset.appLogDate = String(log.date || '');
    row.dataset.appLogType = String(log.log_type || 'Info');
    row.dataset.appLogAction = String(log.action || '');
    const values = [log.id, log.username, log.executed_by || '—'];
    const idCell = document.createElement('td'); idCell.textContent = String(values[0] ?? ''); row.append(idCell);
    const dateCell = document.createElement('td');
    dateCell.className = 'app-log-date';
    const [datePart, timePart] = String(log.created_at || '').split(' ');
    dateCell.append(datePart || '—');
    if (timePart) dateCell.append(document.createElement('br'), timePart);
    row.append(dateCell);
    values.slice(1).forEach((value) => { const cell = document.createElement('td'); cell.textContent = String(value ?? ''); row.append(cell); });
    const typeCell = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `log-type-badge log-type-${String(log.log_type || 'Info').toLocaleLowerCase()}`;
    badge.textContent = String(log.log_type || 'Info');
    typeCell.append(badge);
    row.append(typeCell);
    const actionCell = document.createElement('td'); actionCell.textContent = String(log.action || ''); row.append(actionCell);
    const detailsCell = document.createElement('td');
    const summary = document.createElement('p'); summary.className = 'app-log-summary'; summary.textContent = String(log.summary || ''); detailsCell.append(summary);
    const details = document.createElement('code'); details.textContent = String(log.details_text || ''); detailsCell.append(details); row.append(detailsCell);
    return row;
  };
  const refreshAppLogs = async ({manual = false} = {}) => {
    if (refreshInProgress || !body || (!manual && document.hidden)) return;
    refreshInProgress = true;
    // Background polling must be visually silent.  Toggling disabled here
    // made the Refresh button flash every five seconds even though the user
    // had not pressed it.
    if (manual && refreshButton) refreshButton.disabled = true;
    try {
      const response = await fetch('/api/app-logs', {headers: {'Accept': 'application/json'}, cache: 'no-store'});
      if (!response.ok) throw new Error('Unable to refresh App Logs.');
      const payload = await response.json();
      const logs = Array.isArray(payload.logs) ? payload.logs : [];
      const nextSnapshot = JSON.stringify(logs);
      if (nextSnapshot !== appLogsSnapshot) {
        const pagePosition = window.scrollY;
        appLogsSnapshot = nextSnapshot;
        rows = logs.map(createAppLogRow);
        body.replaceChildren(...rows, ...(noResults ? [noResults] : []));
        if (count) count.textContent = `${logs.length} entries`;
        syncAppLogRows();
        restorePagePosition(pagePosition);
      }
      if (!executionStreamConnected) renderExecutionLogs(payload.execution_logs);
    } catch (_error) {
      // Keep the last successfully rendered snapshot if a polling request fails.
    } finally {
      refreshInProgress = false;
      if (manual && refreshButton) refreshButton.disabled = false;
    }
  };
  [userFilter, executorFilter, dateFilter, typeFilter, actionFilter].filter(Boolean).forEach((filter) => filter.addEventListener('change', () => {
    persistAppLogFilters();
    syncAppLogRows({resetMobilePage: true});
  }));
  clearFilters?.addEventListener('click', () => {
    if (userFilter) userFilter.value = 'all';
    if (executorFilter) executorFilter.value = 'all';
    if (dateFilter) dateFilter.value = 'all';
    if (typeFilter) typeFilter.value = 'all';
    if (actionFilter) actionFilter.value = 'all';
    try { window.localStorage.removeItem(appLogFiltersStorageKey); } catch (_error) { /* Ignore unavailable browser storage. */ }
    syncAppLogRows({resetMobilePage: true});
  });
  refreshButton?.addEventListener('click', () => refreshAppLogs({manual: true}));
  if (executionLogOutput && 'EventSource' in window) {
    const executionLogStream = new EventSource('/api/app-logs/execution-stream');
    executionLogStream.addEventListener('open', () => { executionStreamConnected = true; });
    executionLogStream.addEventListener('message', (event) => {
      try {
        renderExecutionLogs(JSON.parse(event.data).execution_logs);
      } catch (_error) {
        // The existing snapshot remains available until the next valid event.
      }
    });
    executionLogStream.addEventListener('error', () => { executionStreamConnected = false; });
    window.addEventListener('pagehide', () => executionLogStream.close(), {once: true});
  }
  window.setInterval(refreshAppLogs, 5000);
  syncAppLogRows({resetMobilePage: true});
}

document.querySelectorAll('[data-chart-aggregation-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const metric = String(select.dataset.metric || '').trim();
    if (!metric) return;
    const selectedAggregation = String(select.value || 'all').trim();
    const globalAggregation = String(select.dataset.globalAggregation || 'all').trim();
    const overrides = parseAggregationOverrides(select.dataset.currentOverrides || '');
    if (!selectedAggregation || selectedAggregation === 'all' || selectedAggregation === globalAggregation) {
      overrides.delete(metric);
    } else {
      overrides.set(metric, selectedAggregation);
    }

    const params = new URLSearchParams(window.location.search);
    const serialized = formatAggregationOverrides(overrides);
    if (serialized) {
      params.set('aggregation_overrides', serialized);
    } else {
      params.delete('aggregation_overrides');
    }
    params.set('load', '1');
    persistDatasetsAnalysisState(params);
    persistActiveDatasetState(params);
    showLoadingOverlay(`Updating ${metric} comparison`);
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-summary-control]').forEach((node) => {
  ['click', 'mousedown', 'mouseup', 'keydown'].forEach((eventName) => {
    node.addEventListener(eventName, (event) => {
      event.stopPropagation();
    });
  });
});

document.querySelectorAll('[data-global-aggregation-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.form || document.getElementById('datasets-analysis-filters-form');
    if (!form) return;
    syncDatasetsAnalysisHiddenControl('aggregation', select.value || 'all');
    const params = buildDatasetsAnalysisParamsFromForm(form);
    params.set('aggregation', String(select.value || 'all'));
    params.set('load', '1');
    params.delete('aggregation_overrides');
    persistDatasetsAnalysisState(params);
    showLoadingOverlay('Updating all chart aggregations');
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-global-cdf-grouping-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.form || document.getElementById('datasets-analysis-filters-form');
    if (!form) return;
    syncDatasetsAnalysisHiddenControl('cdf_grouping', select.value || 'all');
    const params = buildDatasetsAnalysisParamsFromForm(form);
    params.set('cdf_grouping', String(select.value || 'all'));
    params.set('load', '1');
    params.delete('cdf_overrides');
    persistDatasetsAnalysisState(params);
    showLoadingOverlay('Updating all CDF comparisons');
    window.location.search = params.toString();
  });
});

document.querySelectorAll('[data-chart-cdf-grouping-select]').forEach((select) => {
  select.addEventListener('change', () => {
    const metric = String(select.dataset.metric || '').trim();
    if (!metric) return;
    const selectedGrouping = String(select.value || 'all').trim();
    const globalGrouping = String(select.dataset.globalCdfGrouping || 'all').trim();
    const overrides = parseAggregationOverrides(select.dataset.currentOverrides || '');
    if (!selectedGrouping || selectedGrouping === 'all' || selectedGrouping === globalGrouping) {
      overrides.delete(metric);
    } else {
      overrides.set(metric, selectedGrouping);
    }
    const params = new URLSearchParams(window.location.search);
    const serialized = formatAggregationOverrides(overrides);
    if (serialized) {
      params.set('cdf_overrides', serialized);
    } else {
      params.delete('cdf_overrides');
    }
    params.set('load', '1');
    persistDatasetsAnalysisState(params);
    persistActiveDatasetState(params);
    showLoadingOverlay(`Updating ${metric} CDF comparison`);
    window.location.search = params.toString();
  });
});

const queueNode = document.querySelector('[data-queue-status-url]');
if (queueNode) {
  const url = queueNode.dataset.queueStatusUrl || '';
  const delay = Number(queueNode.dataset.queuePollMs || '0');
  let refreshWorkspaceAfterCompletion = false;
  const selectedDatasetField = document.querySelector('input[name="dataset_id"], select[name="dataset_id"]');
  const waitingPanel = document.querySelector('.queue-waiting-copy');
  const queueTypeFilter = document.querySelector('[data-queue-type-filter]');
  const sortableQueueTable = queueNode.querySelector('[data-queue-sortable-table]');
  const queueSortButtons = Array.from(sortableQueueTable?.querySelectorAll('[data-queue-sort-key]') || []);
  const queueSortState = {key: 'id', direction: 'desc'};
  const formatQueueCount = (value) => Math.max(0, Number(value) || 0).toLocaleString('en-US', {maximumFractionDigits: 0});
  const applyQueueSort = () => {
    const body = sortableQueueTable?.tBodies?.[0];
    if (!body) return;
    const button = queueSortButtons.find((candidate) => candidate.dataset.queueSortKey === queueSortState.key);
    const type = button?.dataset.queueSortType || 'text';
    const direction = queueSortState.direction === 'desc' ? -1 : 1;
    const rows = Array.from(body.querySelectorAll('tr[data-dataset-id]'));
    rows.sort((left, right) => {
      const leftValue = left.querySelector(`[data-queue-sort-cell="${queueSortState.key}"]`)?.dataset.queueSortValue || '';
      const rightValue = right.querySelector(`[data-queue-sort-cell="${queueSortState.key}"]`)?.dataset.queueSortValue || '';
      let compared;
      if (type === 'number') {
        compared = (Number(leftValue) || 0) - (Number(rightValue) || 0);
      } else {
        compared = leftValue.localeCompare(rightValue, undefined, {numeric: true, sensitivity: 'base'});
      }
      if (compared === 0) compared = Number(left.dataset.datasetId || 0) - Number(right.dataset.datasetId || 0);
      return compared * direction;
    });
    const combinedBoundary = body.querySelector('[data-combined-dataset-structure-row], [data-combined-dataset-row]');
    rows.forEach((row) => body.insertBefore(row, combinedBoundary));
    queueSortButtons.forEach((candidate) => {
      const active = candidate.dataset.queueSortKey === queueSortState.key;
      const heading = candidate.closest('th');
      if (heading) heading.setAttribute('aria-sort', active ? (queueSortState.direction === 'desc' ? 'descending' : 'ascending') : 'none');
      const indicator = candidate.querySelector('[data-queue-sort-indicator]');
      if (indicator) indicator.textContent = active ? (queueSortState.direction === 'desc' ? '↓' : '↑') : '↕';
    });
    sortableQueueTable.dispatchEvent(new CustomEvent('mobile-card-pagination:refresh', {bubbles: true}));
  };
  queueSortButtons.forEach((button) => button.addEventListener('click', () => {
    const key = button.dataset.queueSortKey || 'id';
    queueSortState.direction = queueSortState.key === key && queueSortState.direction === 'asc' ? 'desc' : 'asc';
    queueSortState.key = key;
    applyQueueSort();
  }));
  applyQueueSort();
  const applyQueueTypeFilter = () => {
    const selectedKind = queueTypeFilter?.value || '';
    const combinedRows = Array.from(document.querySelectorAll('[data-combined-dataset-row]'));
    document.querySelectorAll('[data-dataset-row]').forEach((row) => {
      row.hidden = Boolean(selectedKind && row.dataset.datasetKind !== selectedKind);
    });
    const hideCombinedStructure = !combinedRows.some((row) => !row.hidden);
    document.querySelectorAll('[data-combined-dataset-structure-row]').forEach((row) => {
      row.hidden = hideCombinedStructure;
    });
    queueNode.querySelector('.queue-table')?.dispatchEvent(new CustomEvent('mobile-card-pagination:refresh', {bubbles: true, detail: {reset: true}}));
  };
  queueTypeFilter?.addEventListener('change', applyQueueTypeFilter);
  applyQueueTypeFilter();
  const formatQueueTimestamp = (value) => String(value || '').replace('T', ' ').replace(' ', '\n');
  const formatQueueElapsed = (value) => {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours) return `${hours}h ${String(minutes).padStart(2, '0')}m ${String(seconds).padStart(2, '0')}s`;
    if (minutes) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
    return `${seconds}s`;
  };

  const updateQueueRow = (dataset) => {
    const row = document.querySelector(`[data-dataset-row][data-dataset-id="${dataset.id}"]`);
    if (!row) return;
    const kind = row.querySelector('[data-queue-kind]');
    const rows = row.querySelector('[data-queue-rows]');
    const columns = row.querySelector('[data-queue-columns]');
    const size = row.querySelector('[data-queue-size]');
    const statusPill = row.querySelector('[data-queue-status-pill]');
    const progressBar = row.querySelector('[data-queue-progress-bar]');
    const progressLabel = row.querySelector('[data-queue-progress-label]');
    const progressPercent = row.querySelector('[data-queue-progress-percent]');
    const progressSeparator = row.querySelector('[data-queue-progress-separator]');
    const elapsed = row.querySelector('[data-queue-elapsed]');
    const uploaded = row.querySelector('[data-queue-uploaded]');
    const updated = row.querySelector('[data-queue-updated]');
    const actions = row.querySelector('.queue-actions');
    let errorNode = row.querySelector('[data-queue-error]');
    const previousStatus = row.dataset.queueStatus
      || (statusPill?.classList.contains('queue-status-ready') ? 'ready' : '');

    if (kind) kind.textContent = dataset.input_kind_label || 'Other';
    if (kind) kind.dataset.queueSortValue = dataset.input_kind_label || 'Other';
    if (rows) { rows.textContent = formatQueueCount(dataset.row_count); rows.dataset.queueSortValue = String(dataset.row_count || 0); }
    if (columns) { columns.textContent = formatQueueCount(dataset.column_count); columns.dataset.queueSortValue = String(dataset.column_count || 0); }
    if (size) { size.textContent = dataset.size_mb_label || '0.00 MB'; size.dataset.queueSortValue = String(dataset.size_bytes || 0); }
    if (statusPill) {
      statusPill.textContent = dataset.status_label || dataset.status || 'Queued';
      statusPill.className = `queue-status-pill queue-status-${dataset.status}`;
    }
    row.dataset.queueStatus = dataset.status || '';
    const statusCell = row.querySelector('[data-queue-sort-cell="status"]');
    const progressCell = row.querySelector('[data-queue-sort-cell="progress"]');
    if (statusCell) statusCell.dataset.queueSortValue = dataset.status_label || dataset.status || 'Queued';
    if (progressCell) progressCell.dataset.queueSortValue = String(dataset.progress || 0);
    if (previousStatus && previousStatus !== 'ready' && dataset.status === 'ready') {
      refreshWorkspaceAfterCompletion = true;
    }
    if (progressBar) {
      progressBar.style.width = `${dataset.progress || 0}%`;
      progressBar.className = `progress-bar status-${dataset.status}`;
    }
    if (progressPercent) progressPercent.textContent = `${dataset.progress || 0}%`;
    else if (progressLabel) progressLabel.textContent = `${dataset.progress || 0}%`;
    if (elapsed) {
      elapsed.textContent = dataset.elapsed_seconds === null || dataset.elapsed_seconds === undefined
        ? '' : formatQueueElapsed(dataset.elapsed_seconds);
      elapsed.hidden = !elapsed.textContent;
      if (progressSeparator) progressSeparator.hidden = elapsed.hidden;
    }
    if (uploaded) {
      uploaded.textContent = formatQueueTimestamp(dataset.uploaded_at_local || dataset.uploaded_at);
      uploaded.dataset.queueSortValue = dataset.uploaded_at || '';
    }
    if (updated) {
      updated.textContent = formatQueueTimestamp(dataset.updated_at_local || dataset.updated_at || dataset.uploaded_at_local || dataset.uploaded_at);
      updated.dataset.queueSortValue = dataset.updated_at || dataset.uploaded_at || '';
    }
    // A profile can be in the small persistence window between status updates.
    // Keep the known row kind until the API supplies a replacement so ready CDR
    // actions do not disappear while another upload is being processed.
    const datasetKind = dataset.dataset_kind || row.dataset.datasetKind || 'generic';
    row.dataset.datasetKind = datasetKind;
    if (dataset.last_error && (dataset.status === 'failed' || dataset.status === 'stopped')) {
      if (!errorNode && progressLabel && progressLabel.parentElement) {
        errorNode = document.createElement('p');
        errorNode.className = 'dataset-error';
        errorNode.setAttribute('data-queue-error', '');
        progressLabel.parentElement.appendChild(errorNode);
      }
      if (errorNode) {
        errorNode.textContent = dataset.last_error;
      }
    } else if (errorNode) {
      errorNode.remove();
    }
    if (actions) {
      const openParams = new URLSearchParams();
      openParams.set('dataset_id', String(dataset.id));
      if (datasetKind && datasetKind !== 'generic') {
        openParams.set('input_kind', String(datasetKind));
      }
      const openHref = `/datasets-analysis?${openParams.toString()}`;
      const isCdr = ['data', 'voice', 'speech'].includes(datasetKind);
      const hadMapVendors = Boolean(actions.querySelector('[data-vendor-map-open]'));
      const hadClearVendors = Boolean(actions.querySelector('[data-vendor-clear-open]'));
      // Preserve already available Vendor actions during live polling. New
      // actions still come directly from the persisted API capabilities.
      const canMapVendors = Boolean(dataset.can_map_vendors) || hadMapVendors;
      const canClearVendors = Boolean(dataset.can_clear_vendors) || hadClearVendors;
      const fileName = String(dataset.file_name || 'dataset')
        .replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const isReady = dataset.status === 'ready';
      const canReprocess = ['ready', 'failed', 'stopped'].includes(dataset.status);
      const canStop = dataset.status === 'processing';
      actions.innerHTML = `
        ${isReady
          ? `<a class="ghost-link action-link-preview" href="/workspace/preview/${dataset.id}" target="_blank" rel="noopener" data-preview-open-link data-loading-label="Generating dataset preview" title="Preview dataset" aria-label="Preview dataset">Preview</a>`
          : '<button type="button" class="ghost-link action-link-preview" disabled title="Preview is only available for ready datasets" aria-label="Preview unavailable">Preview</button>'}
        ${isReady && isCdr
          ? `<a class="ghost-link action-link-primary" href="${openHref}" data-datasets-analysis-open-link data-dataset-id="${dataset.id}" title="Show analysis" aria-label="Show analysis"${datasetKind ? ` data-input-kind="${String(datasetKind)}"` : ''}>Show Analysis</a>`
          : '<button type="button" class="ghost-link action-link-primary" disabled title="Analysis is only available for ready CDR datasets" aria-label="Analysis unavailable">Show Analysis</button>'}
        ${canMapVendors
          ? `<button type="button" class="ghost-link action-link-map-vendors" data-vendor-map-open data-dataset-id="${dataset.id}" data-dataset-name="${fileName}" title="Map vendors" aria-label="Map vendors">Map Vendors</button>`
          : '<button type="button" class="ghost-link action-link-map-vendors" disabled title="Vendor mapping is not available for this dataset" aria-label="Map vendors unavailable">Map Vendors</button>'}
        ${canClearVendors
          ? `<button type="button" class="action-link-clear-vendors" data-vendor-clear-open data-dataset-id="${dataset.id}" title="Clear vendor mapping" aria-label="Clear vendor mapping">Clear Vendors</button>`
          : '<button type="button" class="action-link-clear-vendors" disabled title="No tool-applied vendor mapping is available to clear" aria-label="Clear vendor mapping unavailable">Clear Vendors</button>'}
        ${canStop
          ? `<form method="post" action="/datasets-analysis/stop/${dataset.id}" data-confirm="Stop processing for '${fileName}'?" data-confirm-title="Stop processing" data-confirm-label="Stop processing"><button type="submit" class="warning-button icon-action action-link-stop" aria-label="Stop processing" title="Stop processing">Stop Processing</button></form>`
          : `<form method="post" action="/datasets-analysis/retry/${dataset.id}" data-confirm="Reprocess dataset '${fileName}' from its source file?" data-confirm-title="Reprocess dataset" data-confirm-label="Reprocess dataset" data-loading-label="Reprocessing dataset"><button type="submit" class="warning-button icon-action action-link-reprocess" aria-label="Reprocess dataset" title="Reprocess dataset"${canReprocess ? '' : ' disabled'}>Reprocess Dataset</button></form>`}
        <form method="post" action="/datasets-analysis/delete/${dataset.id}" data-confirm="Delete dataset '${fileName}'?" data-confirm-title="Delete dataset" data-confirm-label="Delete dataset">
          <button type="submit" class="danger-button icon-action" aria-label="Delete dataset" title="Delete dataset"${canStop ? ' disabled' : ''}>Delete Dataset</button>
        </form>
      `;
      applyQueueTypeFilter();
      actions.querySelectorAll('form[data-confirm]').forEach((form) => {
        form.addEventListener('submit', async (event) => {
          event.preventDefault();
          const accepted = await showConfirmDialog(form.dataset.confirm, {
            title: form.dataset.confirmTitle || 'Confirm action',
            confirmLabel: form.dataset.confirmLabel || 'Confirm',
          });
          if (accepted) {
            form.submit();
          }
        });
      });
    }
  };

  const updateCombinedQueueRow = (combined) => {
    const row = document.querySelector(`[data-combined-dataset-row][data-dataset-kind="${combined.kind}"]`);
    if (!(row instanceof HTMLTableRowElement)) return;
    const rows = row.querySelector('[data-combined-dataset-rows]');
    const columns = row.querySelector('[data-combined-dataset-columns]');
    const status = row.querySelector('[data-combined-dataset-status]');
    const bar = row.querySelector('[data-combined-dataset-progress-bar]');
    const percent = row.querySelector('[data-combined-dataset-progress-percent]');
    const updated = row.querySelector('[data-combined-dataset-updated]');
    const warning = Boolean(combined.has_missing_rows || combined.is_recalculating || combined.needs_recalculation);
    const statusLabel = combined.is_recalculating ? 'Recalculating' : combined.has_missing_rows
      ? 'Missing Rows' : combined.needs_recalculation ? 'Recalc Needed' : 'Ready';
    const progressValue = Number.isFinite(Number(combined.recreation_progress))
      ? Math.max(0, Math.min(100, Number(combined.recreation_progress))) : 100;
    if (rows instanceof HTMLElement) rows.textContent = formatQueueCount(combined.row_count);
    if (columns instanceof HTMLElement) columns.textContent = formatQueueCount(combined.column_count);
    if (updated instanceof HTMLElement) updated.textContent = combined.updated_at_label || '—';
    row.classList.toggle('combined-dataset-ready', !warning);
    row.classList.toggle('combined-dataset-warning', warning);
    if (status instanceof HTMLElement) {
      status.className = `queue-status-pill queue-status-${warning ? 'warning' : 'ready'}`;
      status.textContent = combined.is_recalculating && combined.recreation_status === 'queued'
        ? 'Queued' : statusLabel;
    }
    if (bar instanceof HTMLElement) {
      bar.className = `progress-bar status-${combined.is_recalculating ? 'processing' : 'ready'}`;
      bar.style.width = `${progressValue}%`;
    }
    if (percent instanceof HTMLElement) percent.textContent = `${progressValue}%`;
    syncCombinedDatasetStopButton(row, {
      active: combined.is_recalculating,
      stopUrl: combined.recreation_stop_url,
      stopTaskId: combined.recreation_stop_task_id,
      combinedName: combined.name,
    });
  };

  const pollQueue = async ({scheduleNext = true, suppressReload = false} = {}) => {
    try {
      const response = await fetch(url, {cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (!response.ok) return;
      const payload = await response.json();
      const datasets = Array.isArray(payload.datasets) ? payload.datasets : [];
      datasets.forEach(updateQueueRow);
      const mapAll = document.querySelector('[data-vendor-map-all-open]');
      const clearAll = document.querySelector('[data-vendor-clear-all-open]');
      const reprocessAll = document.querySelector('[data-reprocess-all-open]');
      const stopAll = document.querySelector('.queue-stop-all');
      const removeAll = document.querySelector('.queue-remove-all');
      if (mapAll instanceof HTMLButtonElement) mapAll.disabled = !datasets.some((dataset) => dataset.can_map_vendors);
      if (clearAll instanceof HTMLButtonElement) clearAll.disabled = !datasets.some((dataset) => dataset.can_clear_vendors);
      if (reprocessAll instanceof HTMLButtonElement) reprocessAll.disabled = !datasets.some((dataset) => dataset.can_reprocess);
      if (stopAll instanceof HTMLButtonElement) stopAll.disabled = !datasets.some((dataset) => ['queued', 'processing'].includes(dataset.status));
      if (removeAll instanceof HTMLButtonElement) removeAll.disabled = datasets.length === 0 || datasets.some((dataset) => dataset.status === 'processing');
      document.dispatchEvent(new CustomEvent('workspace-dataset-status-updated', {detail: {datasets}}));
      const combinedTables = Array.isArray(payload.combined_tables) ? payload.combined_tables : [];
      combinedTables.forEach(updateCombinedQueueRow);
      applyQueueSort();
      applyQueueTypeFilter();
      if (refreshWorkspaceAfterCompletion) {
        if (suppressReload) {
          refreshWorkspaceAfterCompletion = false;
        } else {
          // A complete reload obtains the final server-rendered action set,
          // including Map/Clear Vendors, after background processing finishes.
          window.location.reload();
          return;
        }
      }
      const selectedDatasetId = selectedDatasetField ? selectedDatasetField.value : '';
      if (waitingPanel && selectedDatasetId) {
        const selected = datasets.find((dataset) => String(dataset.id) === String(selectedDatasetId));
        if (selected) {
          waitingPanel.innerHTML = `The dataset queue is updating live. Current state: <strong>${selected.status_label}</strong>.`;
          if (selected.status === 'ready') {
            window.location.reload();
          }
        }
      }
    } catch (_error) {
      // Ignore transient polling errors and keep the current UI state.
    } finally {
      if (scheduleNext && delay > 0) {
        window.setTimeout(pollQueue, delay);
      }
    }
  };

  window.addEventListener('workspace-dataset-table-refresh-requested', () => {
    void pollQueue({scheduleNext: false, suppressReload: true});
  });

  if (url && delay > 0) {
    window.setTimeout(pollQueue, delay);
  }
}

(() => {
  if (!document.body.dataset.authenticatedUser) return;
  const root = document.getElementById('background-task-panels');
  if (!(root instanceof HTMLElement)) return;
  const activeDock = root.querySelector('[data-background-task-dock="active"]');
  const otherDock = root.querySelector('[data-background-task-dock="other"]');
  const systemDock = root.querySelector('[data-background-task-dock="system"]');
  if (!(activeDock instanceof HTMLElement) || !(otherDock instanceof HTMLElement) || !(systemDock instanceof HTMLElement)) return;
  let polling = false;
  let pollingStopped = false;
  let pollingInterval = null;
  let renderedSignature = '';
  let serverGroups = [];
  let previousServerTasks = new Map();
  const completedServerTasks = new Map();
  const locallyStoppedTaskIds = new Set();
  const transientTasks = new Map();
  const minimizedPanels = new Map();
  const panelScrollPositions = new Map();
  const completedTaskRetentionMs = 5000;
  let completedTaskExpiryTimer = null;
  const formatTaskDuration = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) return '';
    if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${Math.round(seconds % 60)}s`;
  };
  const taskIsQueued = (task) => String(task?.status || '').toLowerCase() === 'queued'
    || String(task?.detail || '').toLowerCase() === 'queued';
  const taskCanStop = (task) => {
    const status = String(task?.status || '').toLowerCase();
    return (typeof task?.cancel === 'function' || Boolean(task?.stop_url && task?.stop_task_id))
      && !['complete', 'completed', 'cancelled', 'stopped', 'ready'].includes(status);
  };
  const requestTaskStop = async (task) => {
    if (typeof task?.cancel === 'function') {
      await task.cancel();
      return;
    }
    const body = new URLSearchParams({task_id: String(task.stop_task_id)});
    const response = await fetch(String(task.stop_url), {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json'}, body,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(String(payload.detail || 'The background job could not be stopped.'));
    }
    locallyStoppedTaskIds.add(String(task.id));
  };
  const formatQueuedAge = (queuedAt) => {
    const timestamp = Number(queuedAt);
    if (!Number.isFinite(timestamp) || timestamp <= 0) return '';
    return `Queued ${Math.max(0, Math.floor((Date.now() / 1000 - timestamp) / 60))}m ago`;
  };

  window.addEventListener('dashboard-analytic:background-task', (event) => {
    const task = event.detail;
    if (!task || !task.id) return;
    if (['complete', 'completed', 'cancelled'].includes(String(task.status || '').toLowerCase())) {
      const previous = transientTasks.get(String(task.id));
      if (previous && String(task.status || '').toLowerCase() !== 'cancelled') {
        const completedAt = Date.now();
        const startedAt = Number(previous.started_at) * 1000 || completedAt;
        completedServerTasks.set(String(task.id), {
          group: {
            workspace_id: previous.workspace_id || '__client__',
            workspace_name: previous.workspace_name || 'Active workspace',
            is_active: Boolean(previous.is_active), tasks: [],
          },
          task: {...previous, status: 'completed', detail: 'Completed', progress: 100, completed_at: completedAt / 1000,
            duration_seconds: Math.max(0, (completedAt - startedAt) / 1000)},
          position: 0, expiresAt: completedAt + completedTaskRetentionMs,
        });
      }
      transientTasks.delete(String(task.id));
    } else {
      const previous = transientTasks.get(String(task.id));
      const queued = taskIsQueued(task);
      const queuedAt = task.queued_at || previous?.queued_at || Date.now() / 1000;
      const startedAt = queued ? null : (task.started_at || previous?.started_at || Date.now() / 1000);
      transientTasks.set(String(task.id), {
        ...task,
        queued_at: queuedAt,
        started_at: startedAt,
        duration_seconds: !queued && task.duration_seconds !== null && task.duration_seconds !== undefined
          && Number.isFinite(Number(task.duration_seconds))
          ? Number(task.duration_seconds)
          : (!queued && startedAt ? Math.max(0, Date.now() / 1000 - Number(startedAt)) : null),
      });
    }
    render(mergedGroups());
  });

  const mergedGroups = () => {
    const groups = serverGroups.map(group => ({...group, tasks: [...(group.tasks || [])]}));
    const completedByWorkspace = new Map();
    completedServerTasks.forEach((completed) => {
      const completedGroup = completed.group;
      let group = groups.find(candidate => String(candidate.workspace_id) === String(completedGroup.workspace_id));
      if (!group) {
        group = {...completedGroup, tasks: []};
        groups.push(group);
      }
      const workspaceId = String(completedGroup.workspace_id);
      const entries = completedByWorkspace.get(workspaceId) || [];
      entries.push({group, ...completed});
      completedByWorkspace.set(workspaceId, entries);
    });
    completedByWorkspace.forEach((entries) => {
      entries.sort((left, right) => left.position - right.position).forEach((entry, offset) => {
        entry.group.tasks.splice(Math.min(entry.position + offset, entry.group.tasks.length), 0, entry.task);
      });
    });
    transientTasks.forEach((task) => {
      const workspaceId = String(task.workspace_id || '__client__');
      let group = groups.find(candidate => String(candidate.workspace_id) === workspaceId);
      if (!group) {
        group = {
          workspace_id: workspaceId,
          workspace_name: String(task.workspace_name || 'Active workspace'),
          is_active: Boolean(task.is_active),
          tasks: [],
        };
        groups.push(group);
      }
      if (task.dashboard_name && String(task.id).startsWith('prepare-')) {
        group.tasks = (group.tasks || []).filter(candidate => (
          !String(candidate.id || '').startsWith('dashboard-prefetch:')
          ||
          !candidate.dashboard_name
          || String(candidate.dashboard_name) !== String(task.dashboard_name)
          || String(candidate.id) === String(task.id)
        ));
      }
      if (!(group.tasks || []).some(candidate => String(candidate.id) === String(task.id))) group.tasks.push(task);
    });
    return groups;
  };

  const retainCompletedServerTasks = (groups) => {
    const now = Date.now();
    const nextTasks = new Map();
    (Array.isArray(groups) ? groups : []).forEach((group) => {
      (Array.isArray(group.tasks) ? group.tasks : []).forEach((task, position) => {
        if (!task?.id) return;
        const previous = previousServerTasks.get(String(task.id));
        const queued = taskIsQueued(task);
        const observedAt = queued ? null : (Number(task.started_at) * 1000 || previous?.observedAt || now);
        if (!queued && !Number(task.started_at)) task.started_at = observedAt / 1000;
        if (queued) {
          task.duration_seconds = null;
        } else if ((task.duration_seconds === null || task.duration_seconds === undefined)
            || !Number.isFinite(Number(task.duration_seconds))) {
          task.duration_seconds = Math.max(0, (now - observedAt) / 1000);
        }
        nextTasks.set(String(task.id), {
          group: {...group, tasks: []}, task: {...task}, position,
          observedAt,
        });
      });
    });
    previousServerTasks.forEach((previous, taskId) => {
      if (nextTasks.has(taskId)) return;
      if (locallyStoppedTaskIds.delete(taskId)) {
        completedServerTasks.delete(taskId);
        return;
      }
      const completedAt = Number(previous.task.completed_at) * 1000 || now;
      const expiresAt = Number.isFinite(completedAt) && completedAt > 0
        ? Math.max(now, completedAt) + completedTaskRetentionMs
        : now + completedTaskRetentionMs;
      const durationSeconds = Number(previous.task.duration_seconds);
      const observedAt = Number(previous.observedAt);
      if (expiresAt <= now) return;
      completedServerTasks.set(taskId, {
        group: previous.group,
        task: {
          ...previous.task, status: 'completed', detail: 'Completed', progress: 100, completed_at: completedAt / 1000,
          duration_seconds: Number.isFinite(durationSeconds)
            ? durationSeconds
            : (Number.isFinite(observedAt) ? Math.max(0, (completedAt - observedAt) / 1000) : 0),
        },
        position: previous.position,
        expiresAt,
      });
    });
    completedServerTasks.forEach((completed, taskId) => {
      if (completed.expiresAt <= now || nextTasks.has(taskId)) completedServerTasks.delete(taskId);
    });
    previousServerTasks = nextTasks;
    if (completedTaskExpiryTimer !== null) window.clearTimeout(completedTaskExpiryTimer);
    const expiries = [...completedServerTasks.values()].map((task) => task.expiresAt);
    if (expiries.length) {
      completedTaskExpiryTimer = window.setTimeout(() => {
        completedTaskExpiryTimer = null;
        const expiredAt = Date.now();
        completedServerTasks.forEach((task, taskId) => {
          if (task.expiresAt <= expiredAt) completedServerTasks.delete(taskId);
        });
        render(mergedGroups());
      }, Math.max(0, Math.min(...expiries) - now + 10));
    } else {
      completedTaskExpiryTimer = null;
    }
  };

  const createTaskPanel = (group) => {
    const panel = document.createElement('section');
    const panelKind = group.workspace_id === '__server__' ? 'system' : (group.is_active ? 'active' : 'other');
    panel.className = `background-task-panel background-task-panel-${panelKind}`;
    panel.setAttribute('aria-label', `Background tasks for ${group.workspace_name || 'workspace'}`);

    const panelStateKey = String(group.workspace_id);
    panel.dataset.backgroundTaskPanelKey = panelStateKey;
    const minimizedKey = `dashboard-analytic:background-task-panel:${group.workspace_id}:minimized`;
    const minimize = document.createElement('button');
    minimize.type = 'button';
    minimize.className = 'background-task-minimize-button';
    minimize.setAttribute('aria-label', 'Minimize background tasks');
    const setMinimized = (value) => {
      panel.classList.toggle('is-minimized', value);
      minimize.textContent = value ? '+' : '−';
      minimize.title = value ? 'Expand background tasks' : 'Minimize background tasks';
      minimize.setAttribute('aria-label', minimize.title);
      minimizedPanels.set(panelStateKey, value);
      try { localStorage.setItem(minimizedKey, String(value)); } catch (_error) { /* Ignore unavailable local storage. */ }
    };
    minimize.addEventListener('click', () => setMinimized(!panel.classList.contains('is-minimized')));
    let minimized = minimizedPanels.get(panelStateKey) === true;
    if (!minimizedPanels.has(panelStateKey)) {
      try { minimized = localStorage.getItem(minimizedKey) === 'true'; } catch (_error) { /* Ignore unavailable local storage. */ }
    }
    setMinimized(minimized);
    panel.append(minimize);

    const positionKey = `dashboard-analytic:background-task-panel:${group.workspace_id}:position`;
    const pin = document.createElement('button');
    pin.type = 'button';
    pin.className = 'background-task-pin-button';
    pin.title = 'Panel is in its default position';
    pin.setAttribute('aria-label', pin.title);
    pin.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2.4"/><path d="M8.5 4H4v4.5M15.5 4H20v4.5M20 15.5V20h-4.5M4 15.5V20h4.5"/></svg>';
    const restorePosition = () => {
      panel.classList.remove('is-detached');
      panel.style.left = '';
      panel.style.top = '';
      pin.disabled = true;
      pin.title = 'Panel is in its default position';
      pin.setAttribute('aria-label', pin.title);
      try { localStorage.removeItem(positionKey); } catch (_error) { /* Ignore unavailable local storage. */ }
    };
    const applyPosition = (position) => {
      if (!position || !Number.isFinite(position.left) || !Number.isFinite(position.top)) return restorePosition();
      panel.classList.add('is-detached');
      panel.style.left = `${position.left}px`;
      panel.style.top = `${position.top}px`;
      pin.disabled = false;
      pin.title = 'Return panel to its default position';
      pin.setAttribute('aria-label', pin.title);
    };
    try { applyPosition(JSON.parse(localStorage.getItem(positionKey) || 'null')); } catch (_error) { restorePosition(); }
    pin.addEventListener('click', restorePosition);
    panel.append(pin);

    let dragging = null;
    const stopDragging = () => {
      if (!dragging) return;
      panel.classList.remove('is-dragging');
      dragging = null;
    };
    panel.addEventListener('pointerdown', (event) => {
      if (
        event.button !== 0
        || !event.target.closest('.background-task-panel-header')
        || event.target.closest('button, a, input, select, textarea, label')
      ) return;
      const bounds = panel.getBoundingClientRect();
      dragging = {offsetX: event.clientX - bounds.left, offsetY: event.clientY - bounds.top};
      panel.classList.add('is-dragging');
      panel.setPointerCapture?.(event.pointerId);
    });
    panel.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      const bounds = panel.getBoundingClientRect();
      const left = Math.max(8, Math.min(event.clientX - dragging.offsetX, window.innerWidth - bounds.width - 8));
      const top = Math.max(8, Math.min(event.clientY - dragging.offsetY, window.innerHeight - bounds.height - 8));
      applyPosition({left, top});
      try { localStorage.setItem(positionKey, JSON.stringify({left, top})); } catch (_error) { /* Ignore unavailable local storage. */ }
    });
    panel.addEventListener('pointerup', stopDragging);
    panel.addEventListener('pointercancel', stopDragging);

    const panelHeader = document.createElement('header');
    panelHeader.className = 'background-task-panel-header';
    const heading = document.createElement('h3');
    heading.className = 'background-task-workspace';
    heading.textContent = group.workspace_id === '__server__'
      ? 'System tasks'
      : group.is_active
      ? `Active workspace · ${group.workspace_name}`
      : String(group.workspace_name || 'Workspace');
    panelHeader.append(heading);
    const tasks = (Array.isArray(group.tasks) ? group.tasks : [])
      .map((task, index) => ({task, index}))
      .sort((left, right) => {
        const leftTime = Number(left.task.queued_at ?? left.task.started_at ?? left.task.completed_at);
        const rightTime = Number(right.task.queued_at ?? right.task.started_at ?? right.task.completed_at);
        if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return leftTime - rightTime;
        if (Number.isFinite(leftTime) !== Number.isFinite(rightTime)) return Number.isFinite(leftTime) ? -1 : 1;
        return left.index - right.index;
      })
      .map(({task}) => task);
    const taskCount = document.createElement('span');
    taskCount.className = 'background-task-count';
    taskCount.textContent = `${tasks.length} task${tasks.length === 1 ? '' : 's'}`;
    taskCount.setAttribute('aria-label', `${tasks.length} total background task${tasks.length === 1 ? '' : 's'}`);
    panelHeader.append(taskCount);

    const stoppableTasks = tasks
      .filter(taskCanStop)
      .sort((left, right) => Number(taskIsQueued(right)) - Number(taskIsQueued(left)));
    if (stoppableTasks.length) {
      const stopAll = document.createElement('button');
      stopAll.type = 'button';
      stopAll.className = 'background-task-stop-all-button';
      stopAll.textContent = 'Stop all';
      stopAll.title = `Stop all ${stoppableTasks.length} interruptible background task${stoppableTasks.length === 1 ? '' : 's'}`;
      stopAll.setAttribute('aria-label', stopAll.title);
      stopAll.addEventListener('click', async () => {
        const accepted = await showConfirmDialog(
          `Stop all ${stoppableTasks.length} interruptible background task${stoppableTasks.length === 1 ? '' : 's'} in “${String(group.workspace_name || 'System tasks')}”?`,
          {title: 'Interrupt all background tasks', confirmLabel: 'Stop all'},
        );
        if (!accepted) return;
        stopAll.disabled = true;
        const outcomes = [];
        // These requests can update the same Workspace database. Process them
        // one at a time so SQLite write coordination cannot leave part of the
        // batch running. Queued work goes first to prevent it from starting
        // while an earlier processing task is being interrupted.
        for (const task of stoppableTasks) {
          try {
            await requestTaskStop(task);
            outcomes.push({status: 'fulfilled', task});
          } catch (error) {
            outcomes.push({status: 'rejected', task, reason: error});
          }
        }
        await poll();
        const failures = outcomes.filter((outcome) => outcome.status === 'rejected');
        if (failures.length) {
          const stoppedCount = outcomes.length - failures.length;
          showInfoDialog(
            `${stoppedCount} task${stoppedCount === 1 ? '' : 's'} stopped; ${failures.length} could not be stopped.`,
            {title: 'Some tasks are still running', tone: 'error'},
          );
          stopAll.disabled = false;
        } else {
          showInfoDialog(
            outcomes.length === 1
              ? 'The background task has been stopped.'
              : `All ${outcomes.length} background tasks have been stopped.`,
            {title: 'Background tasks stopped', tone: 'info'},
          );
        }
      });
      panelHeader.append(stopAll);
    }
    panel.append(panelHeader);

    const list = document.createElement('div');
    list.className = 'background-task-list';
    tasks.forEach((task) => {
      const dashboardName = String(task.dashboard_name || '');
      const item = document.createElement('div');
      item.className = 'background-task-item';

      const taskHead = document.createElement('div');
      taskHead.className = 'background-task-head';
      const label = document.createElement('span');
      label.className = 'background-task-label';
      label.textContent = dashboardName
        ? `Dashboard “${dashboardName}”: ${String(task.label || 'Background task')}`
        : String(task.label || 'Background task');
      taskHead.append(label);
      if (taskCanStop(task)) {
        const stop = document.createElement('button');
        stop.type = 'button';
        stop.className = 'background-task-stop-button';
        stop.textContent = '■';
        stop.title = 'Interrupt task';
        stop.setAttribute('aria-label', 'Interrupt task');
        stop.addEventListener('click', async () => {
          const accepted = await showConfirmDialog(
            `Stop “${String(task.label || 'this background job')}”?`,
            {title: 'Interrupt background task', confirmLabel: 'Interrupt'},
          );
          if (!accepted) return;
          stop.disabled = true;
          try {
            await requestTaskStop(task);
            await poll();
          } catch (error) {
            stop.disabled = false;
            showInfoDialog(error instanceof Error ? error.message : 'The background task could not be interrupted.', {title: 'Interrupt task', tone: 'error'});
          }
        });
        taskHead.append(stop);
      }
      item.append(taskHead);

      const detail = document.createElement('span');
      detail.className = 'background-task-detail';
      const numericProgress = Number(task.progress);
      const queued = taskIsQueued(task);
      const hasProgress = !queued && task.progress !== null && task.progress !== undefined && Number.isFinite(numericProgress);
      const duration = Number(task.duration_seconds);
      const queuedLabel = queued ? formatQueuedAge(task.queued_at) : '';
      const taskDetail = queuedLabel || String(task.detail || 'Processing');
      detail.textContent = `${taskDetail}${hasProgress ? ` · ${Math.round(Math.max(0, Math.min(100, numericProgress)))}%` : ''}${!queuedLabel && formatTaskDuration(duration) ? ` · ${formatTaskDuration(duration)}` : ''}`;
      item.append(detail);

      const progress = document.createElement('div');
      progress.className = 'background-task-progress';
      progress.setAttribute('role', 'progressbar');
      progress.setAttribute('aria-label', String(task.label || 'Background task'));
      const bar = document.createElement('div');
      bar.className = 'background-task-progress-bar';
      if (queued) {
        progress.hidden = true;
        progress.setAttribute('aria-valuetext', 'Queued');
      } else if (!hasProgress) {
        progress.classList.add('is-indeterminate');
        progress.setAttribute('aria-valuetext', 'In progress');
      } else {
        const boundedProgress = Math.max(0, Math.min(100, numericProgress));
        progress.setAttribute('aria-valuemin', '0');
        progress.setAttribute('aria-valuemax', '100');
        progress.setAttribute('aria-valuenow', String(Math.round(boundedProgress)));
        bar.style.width = `${boundedProgress}%`;
      }
      progress.append(bar);
      item.append(progress);
      list.append(item);
    });
    panel.append(list);
    list.dataset.restoreScrollTop = String(panelScrollPositions.get(panelStateKey) || 0);
    list.addEventListener('scroll', () => {
      if (list.dataset.restoringScroll === 'true') return;
      panelScrollPositions.set(panelStateKey, list.scrollTop);
    }, {passive: true});
    return panel;
  };

  const render = (groups) => {
    const normalized = Array.isArray(groups) ? groups.filter((group) => Array.isArray(group.tasks) && group.tasks.length) : [];
    const visiblePanelKeys = new Set(normalized.map(group => String(group.workspace_id)));
    minimizedPanels.forEach((_value, key) => {
      if (!visiblePanelKeys.has(key)) minimizedPanels.delete(key);
    });
    panelScrollPositions.forEach((_value, key) => { if (!visiblePanelKeys.has(key)) panelScrollPositions.delete(key); });
    const queuedAgeSignature = normalized.flatMap(group => group.tasks || []).filter(taskIsQueued).map((task) => {
      const queuedAt = Number(task.queued_at);
      return `${task.id}:${Number.isFinite(queuedAt) ? Math.max(0, Math.floor((Date.now() / 1000 - queuedAt) / 60)) : ''}`;
    });
    const signature = JSON.stringify([normalized, queuedAgeSignature]);
    if (signature === renderedSignature) return;
    renderedSignature = signature;
    const existingPanels = new Map();
    root.querySelectorAll('[data-background-task-panel-key]').forEach((panel) => {
      const panelKey = panel.dataset.backgroundTaskPanelKey;
      const list = panel.querySelector('.background-task-list');
      if (panelKey && list) panelScrollPositions.set(panelKey, list.scrollTop);
      if (panelKey) existingPanels.set(panelKey, panel);
    });
    const activeGroups = normalized.filter((group) => String(group.workspace_id) !== '__server__' && (Boolean(group.is_active) || group.dock === 'right'));
    const systemGroups = normalized.filter((group) => String(group.workspace_id) === '__server__');
    const otherGroups = normalized.filter((group) => !group.is_active && group.dock !== 'right' && String(group.workspace_id) !== '__server__');
    const refreshPanel = (group) => {
      const panelKey = String(group.workspace_id);
      const replacement = createTaskPanel(group);
      const panel = existingPanels.get(panelKey);
      if (!(panel instanceof HTMLElement)) return replacement;
      const list = panel.querySelector('.background-task-list');
      const replacementList = replacement.querySelector('.background-task-list');
      const header = panel.querySelector('.background-task-panel-header');
      const replacementHeader = replacement.querySelector('.background-task-panel-header');
      if (list instanceof HTMLElement && replacementList instanceof HTMLElement) {
        const preservedScrollTop = panelScrollPositions.get(panelKey) ?? list.scrollTop;
        list.dataset.restoreScrollTop = String(preservedScrollTop);
        list.dataset.restoringScroll = 'true';
        list.replaceChildren(...replacementList.childNodes);
      }
      if (header instanceof HTMLElement && replacementHeader instanceof HTMLElement) {
        header.replaceWith(replacementHeader);
      }
      const preservedClasses = ['is-minimized', 'is-detached', 'is-dragging']
        .filter((className) => panel.classList.contains(className));
      panel.className = [replacement.className, ...preservedClasses].join(' ');
      panel.setAttribute('aria-label', replacement.getAttribute('aria-label') || 'Background tasks');
      return panel;
    };
    activeDock.replaceChildren(...activeGroups.map(refreshPanel));
    otherDock.replaceChildren(...otherGroups.map(refreshPanel));
    systemDock.replaceChildren(...systemGroups.map(refreshPanel));
    root.querySelectorAll('[data-restore-scroll-top]').forEach((list) => {
      const restoredScrollTop = Number(list.dataset.restoreScrollTop) || 0;
      list.dataset.restoringScroll = 'true';
      list.scrollTop = restoredScrollTop;
      const panelKey = list.closest('[data-background-task-panel-key]')?.dataset.backgroundTaskPanelKey;
      delete list.dataset.restoreScrollTop;
      window.requestAnimationFrame(() => {
        list.scrollTop = restoredScrollTop;
        if (panelKey) panelScrollPositions.set(panelKey, list.scrollTop);
        delete list.dataset.restoringScroll;
      });
    });
    root.classList.toggle('has-both-sides', activeGroups.length > 0 && otherGroups.length > 0);
    root.classList.toggle('has-three-docks', activeGroups.length > 0 && otherGroups.length > 0 && systemGroups.length > 0);
    root.hidden = normalized.length === 0;
  };

  const poll = async () => {
    if (polling || pollingStopped) return;
    polling = true;
    try {
      const response = await fetch('/api/background-tasks', {
        credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'},
      });
      if (response.status === 401) {
        pollingStopped = true;
        if (pollingInterval !== null) window.clearInterval(pollingInterval);
        return;
      }
      if (!response.ok) return;
      const payload = await response.json();
      if (payload.authenticated === false) {
        pollingStopped = true;
        if (pollingInterval !== null) window.clearInterval(pollingInterval);
        return;
      }
      serverGroups = Array.isArray(payload.groups) ? payload.groups : [];
      retainCompletedServerTasks(serverGroups);
      render(mergedGroups());
    } catch (_error) {
      // A transient polling failure must not interfere with the current page.
    } finally {
      polling = false;
    }
  };

  poll();
  pollingInterval = window.setInterval(poll, 2000);
  window.addEventListener('dashboard-analytic:refresh-background-tasks', poll);
  window.addEventListener('focus', poll);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
})();

/* Searchable timezone picker for application configuration. */
document.querySelectorAll('[data-configuration-timezone-picker]').forEach((picker) => {
  const input = picker.querySelector('[data-configuration-timezone-input]');
  const toggle = picker.querySelector('[data-configuration-timezone-toggle]');
  const menu = picker.querySelector('[data-configuration-timezone-menu]');
  const options = Array.from(menu?.querySelectorAll('[data-timezone]') || []);
  if (!input || !toggle || !menu) return;

  const setOpen = (open) => {
    menu.hidden = !open;
    input.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-expanded', String(open));
  };
  const filterOptions = () => {
    const term = input.value.trim().toLocaleLowerCase();
    options.forEach((option) => {
      option.hidden = Boolean(term) && !String(option.dataset.timezone || '').toLocaleLowerCase().includes(term);
    });
  };
  const selectTimezone = (timezone) => {
    input.value = timezone;
    filterOptions();
    setOpen(false);
    input.focus();
  };

  input.addEventListener('focus', () => { filterOptions(); setOpen(true); });
  input.addEventListener('input', () => { filterOptions(); setOpen(true); });
  toggle.addEventListener('click', () => {
    const opening = menu.hidden;
    filterOptions();
    setOpen(opening);
    if (opening) input.focus();
  });
  options.forEach((option) => option.addEventListener('mousedown', (event) => {
    event.preventDefault();
    selectTimezone(String(option.dataset.timezone || ''));
  }));
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setOpen(false);
    if (event.key === 'ArrowDown' && menu.hidden) {
      event.preventDefault();
      filterOptions();
      setOpen(true);
    }
  });
  document.addEventListener('click', (event) => {
    if (!picker.contains(event.target)) setOpen(false);
  });
});

/* Reusable Excel-style value filters for compact job tables. */
window.enableExcelColumnFilters = (table, {onChange, excludeLastColumn = true} = {}) => {
  if (!table || table._excelColumnFilters) return table?._excelColumnFilters || null;
  const headers = Array.from(table.tHead?.rows[0]?.cells || []);
  const selectedByColumn = new Map();
  let openMenu = null;
  const valueFor = (row, index) => String(row.cells[index]?.dataset.filterValue ?? row.cells[index]?.textContent ?? '').trim();
  const rows = () => Array.from(table.tBodies[0]?.rows || []);
  const matches = (row) => [...selectedByColumn].every(([index, accepted]) => accepted.has(valueFor(row, index)));
  const apply = () => {
    if (onChange) { onChange(); return; }
    rows().forEach((row) => { row.hidden = !matches(row); });
  };
  const closeMenu = () => {
    if (!openMenu) return;
    openMenu.trigger.setAttribute('aria-expanded', 'false');
    openMenu.menu.remove(); openMenu = null;
  };
  const controller = {matches, apply};
  table._excelColumnFilters = controller;
  table.classList.add('excel-filter-table');
  headers.forEach((header, index) => {
    if (excludeLastColumn && index === headers.length - 1) return;
    const label = header.textContent.trim();
    const trigger = document.createElement('button');
    trigger.type = 'button'; trigger.className = 'excel-column-filter-trigger';
    trigger.setAttribute('aria-label', `Filter ${label}`);
    trigger.setAttribute('aria-haspopup', 'dialog'); trigger.setAttribute('aria-expanded', 'false');
    const caption = document.createElement('span'); caption.className = 'excel-column-filter-caption'; caption.textContent = label;
    const icon = document.createElement('span'); icon.className = 'excel-column-filter-icon'; icon.textContent = '▾'; icon.setAttribute('aria-hidden', 'true');
    trigger.append(caption, icon); header.replaceChildren(trigger);
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      if (openMenu?.trigger === trigger) { closeMenu(); return; }
      closeMenu();
      const values = [...new Set(rows().map((row) => valueFor(row, index)))].sort((left, right) => left.localeCompare(right, undefined, {numeric: true, sensitivity: 'base'}));
      const selected = new Set(selectedByColumn.get(index) || values);
      const menu = document.createElement('section'); menu.className = 'excel-column-filter-menu'; menu.setAttribute('role', 'dialog'); menu.setAttribute('aria-label', `Filter ${label}`);
      const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search values'; search.autocomplete = 'off'; search.setAttribute('aria-label', `Search ${label} values`);
      const toolbar = document.createElement('div'); toolbar.className = 'excel-column-filter-toolbar';
      const selectAll = document.createElement('button'); selectAll.type = 'button'; selectAll.textContent = 'Select all';
      const clear = document.createElement('button'); clear.type = 'button'; clear.textContent = 'Clear'; toolbar.append(selectAll, clear);
      const options = document.createElement('div'); options.className = 'excel-column-filter-options';
      values.forEach((value) => {
        const option = document.createElement('label'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = value; checkbox.checked = selected.has(value);
        const text = document.createElement('span'); text.textContent = value || '(Blank)'; option.append(checkbox, text); options.append(option);
      });
      const footer = document.createElement('div'); footer.className = 'excel-column-filter-footer';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
      const confirm = document.createElement('button'); confirm.type = 'button'; confirm.textContent = 'Apply'; footer.append(cancel, confirm);
      menu.append(search, toolbar, options, footer); document.body.append(menu);
      const bounds = trigger.getBoundingClientRect(), width = Math.min(300, window.innerWidth - 20);
      menu.style.width = `${width}px`; menu.style.left = `${Math.max(10, Math.min(bounds.left, window.innerWidth - width - 10))}px`;
      const below = bounds.bottom + 5, height = menu.offsetHeight;
      menu.style.top = `${below + height <= window.innerHeight - 10 ? below : Math.max(10, bounds.top - height - 5)}px`;
      openMenu = {menu, trigger}; trigger.setAttribute('aria-expanded', 'true');
      search.addEventListener('input', () => { const term = search.value.trim().toLocaleLowerCase(); options.querySelectorAll('label').forEach((option) => { option.hidden = Boolean(term) && !option.textContent.toLocaleLowerCase().includes(term); }); });
      selectAll.addEventListener('click', () => options.querySelectorAll('input').forEach((input) => { input.checked = true; }));
      clear.addEventListener('click', () => options.querySelectorAll('input').forEach((input) => { input.checked = false; }));
      cancel.addEventListener('click', closeMenu);
      confirm.addEventListener('click', () => {
        const accepted = new Set([...options.querySelectorAll('input:checked')].map((input) => input.value));
        if (accepted.size === values.length) selectedByColumn.delete(index); else selectedByColumn.set(index, accepted);
        header.classList.toggle('has-excel-column-filter', selectedByColumn.has(index)); apply(); closeMenu();
      });
      menu.addEventListener('click', (menuEvent) => menuEvent.stopPropagation()); requestAnimationFrame(() => search.focus());
    });
  });
  document.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenu(); });
  return controller;
};
