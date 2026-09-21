(() => {
  'use strict';

  const STORAGE_KEY = 'pasi:control-center';
  const TELEMETRY_INTERVAL_MS = 5000;

  const defaultState = () => ({
    rawRoadmapName: '',
    rawRoadmap: '',
    tasks: [],
    preferredOrder: [],
    hardwareProfile: 'satellite',
    dissection: {
      status: 'not-started',
      progress: 0,
      pass: 0,
      message: 'Awaiting roadmap input'
    }
  });

  let state = defaultState();
  let telemetryTimer = null;
  let telemetryInFlight = false;

  const byId = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function compact(value, max = 180) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  function normalizeTasks(parsed) {
    const rawTasks = Array.isArray(parsed) ? parsed : parsed?.tasks;
    if (!Array.isArray(rawTasks)) return [];

    const ids = new Set();
    return rawTasks.flatMap((raw) => {
      if (!raw || typeof raw !== 'object') return [];
      const id = typeof raw.id === 'string' ? raw.id.trim() : '';
      const title = typeof raw.title === 'string' ? raw.title.trim() : '';
      if (!id || !title || ids.has(id)) return [];
      ids.add(id);
      const dependsOn = Array.isArray(raw.depends_on)
        ? raw.depends_on.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim())
        : [];
      const status = typeof raw.status === 'string' ? raw.status.trim().toLowerCase() : 'pending';
      return [{
        id,
        title,
        objective: typeof raw.objective === 'string' ? raw.objective.trim() : '',
        depends_on: dependsOn,
        status: ['pending', 'blocked', 'cancelled', 'decomposed', 'completed'].includes(status) ? status : 'pending',
        priority: Number.isFinite(Number(raw.priority)) ? Number(raw.priority) : 0
      }];
    });
  }

  function preferredOrderFor(tasks, order) {
    const ids = new Set(tasks.map((task) => task.id));
    const existing = Array.isArray(order) ? order.filter((id) => ids.has(id)) : [];
    const missing = tasks.map((task) => task.id).filter((id) => !existing.includes(id));
    return [...existing, ...missing];
  }

  function orderedTasks(tasks = state.tasks, order = state.preferredOrder) {
    const byTaskId = new Map(tasks.map((task) => [task.id, task]));
    return preferredOrderFor(tasks, order).map((id) => byTaskId.get(id)).filter(Boolean);
  }

  function orderSatisfiesDependencies(tasks) {
    const positions = new Map(tasks.map((task, index) => [task.id, index]));
    return tasks.every((task) =>
      task.depends_on.every((dependency) => {
        const dependencyPosition = positions.get(dependency);
        return dependencyPosition !== undefined && dependencyPosition < positions.get(task.id);
      })
    );
  }

  function reorderedTaskOrder(fromIndex, toIndex) {
    const ordered = orderedTasks();
    if (fromIndex < 0 || toIndex < 0 || fromIndex >= ordered.length || toIndex >= ordered.length || fromIndex === toIndex) {
      return null;
    }
    const next = [...ordered];
    const moved = next.splice(fromIndex, 1)[0];
    next.splice(toIndex, 0, moved);
    if (!orderSatisfiesDependencies(next)) return null;
    return next.map((task) => task.id);
  }

  function setPreferredOrder(order) {
    const nextTasks = orderedTasks(state.tasks, order);
    if (!orderSatisfiesDependencies(nextTasks)) {
      throw new Error('That order violates a task dependency.');
    }
    state.preferredOrder = nextTasks.map((task) => task.id);
  }

  function statusLabel(status) {
    return String(status || 'pending').toUpperCase();
  }

  async function persistState() {
    await chrome.storage.local.set({ [STORAGE_KEY]: state });
  }

  async function loadState() {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    const saved = stored?.[STORAGE_KEY];
    if (!saved || typeof saved !== 'object') return;
    state = {
      ...defaultState(),
      ...saved,
      dissection: { ...defaultState().dissection, ...(saved.dissection || {}) }
    };
    state.preferredOrder = preferredOrderFor(state.tasks, state.preferredOrder);
  }

  function renderDissection() {
    const progress = Math.max(0, Math.min(100, Number(state.dissection.progress) || 0));
    byId('dissection-progress').value = progress;
    byId('dissection-progress-label').textContent = progress + '%';
    byId('dissection-message').textContent = compact(state.dissection.message || 'Awaiting roadmap input', 95);
    byId('dissection-pass').textContent = state.dissection.pass > 0 ? 'Pass ' + state.dissection.pass : 'No dissection pass is active.';
    byId('task-count').textContent = state.tasks.length + ' ' + (state.tasks.length === 1 ? 'task' : 'tasks');
  }

  function renderTasks() {
    const list = byId('task-list');
    const tasks = orderedTasks();
    if (!tasks.length) {
      list.innerHTML = '<div class="empty-state">Import a roadmap to populate the queue. Dependency validation stays authoritative in the Hybrid Planner.</div>';
      return;
    }

    list.innerHTML = tasks.map((task, index) => {
      const dependencyText = task.depends_on.length ? '<p class="muted">Depends on: ' + escapeHtml(task.depends_on.join(', ')) + '</p>' : '';
      const objectiveText = task.objective ? '<p class="task-objective">' + escapeHtml(compact(task.objective, 220)) + '</p>' : '';
      return '<article class="task-card" draggable="true" tabindex="0" data-task-id="' + escapeHtml(task.id) + '" data-index="' + index + '" data-status="' + escapeHtml(task.status) + '">' +
        '<div class="task-head"><div><div class="task-title">' + escapeHtml(task.title) + '</div><div class="task-meta">' +
        '<span class="badge">' + escapeHtml(task.id) + '</span><span class="badge">' + escapeHtml(statusLabel(task.status)) + '</span><span class="badge">P' + escapeHtml(task.priority) + '</span>' +
        '</div></div></div>' +
        objectiveText + dependencyText +
        '<div class="task-actions">' +
        '<button class="icon-button" type="button" data-move="up" data-index="' + index + '" aria-label="Move ' + escapeHtml(task.title) + ' up">Move up</button>' +
        '<button class="icon-button" type="button" data-move="down" data-index="' + index + '" aria-label="Move ' + escapeHtml(task.title) + ' down">Move down</button>' +
        '</div></article>';
    }).join('');

    list.querySelectorAll('[data-move]').forEach((button) => {
      button.addEventListener('click', () => {
        const index = Number(button.dataset.index);
        const delta = button.dataset.move === 'up' ? -1 : 1;
        if (tryMoveTask(index, index + delta)) renderTasks();
      });
    });

    list.querySelectorAll('.task-card').forEach((card) => {
      card.addEventListener('dragstart', (event) => {
        card.dataset.dragging = 'true';
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', card.dataset.index);
      });
      card.addEventListener('dragend', () => delete card.dataset.dragging);
      card.addEventListener('dragover', (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
      });
      card.addEventListener('drop', (event) => {
        event.preventDefault();
        const fromIndex = Number(event.dataTransfer.getData('text/plain'));
        const toIndex = Number(card.dataset.index);
        if (tryMoveTask(fromIndex, toIndex)) renderTasks();
      });
      card.addEventListener('keydown', (event) => {
        if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        const nextIndex = event.key === 'ArrowUp' ? index - 1 : index + 1;
        if (tryMoveTask(index, nextIndex)) renderTasks();
      });
    });
  }

  function tryMoveTask(fromIndex, toIndex) {
    const nextOrder = reorderedTaskOrder(fromIndex, toIndex);
    if (!nextOrder) {
      window.alert('Cannot move that task because the resulting order would violate a dependency. The Hybrid Planner remains authoritative.');
      return false;
    }
    state.preferredOrder = nextOrder;
    void persistState();
    return true;
  }

  function renderAll() {
    renderDissection();
    renderTasks();
    byId('hardware-profile').value = state.hardwareProfile;
  }

  function setOverallStatus(status, label) {
    const chip = byId('overall-status');
    chip.dataset.status = status;
    byId('overall-status-text').textContent = label;
  }

  function observationData(payload) {
    const observation = payload?.observation && typeof payload.observation === 'object' ? payload.observation : payload;
    const data = observation?.data && typeof observation.data === 'object' ? observation.data : observation;
    return { observation, data };
  }

  function observationAgeMs(observation) {
    const value = Date.parse(String(observation?.captured_at || ''));
    return Number.isFinite(value) ? Math.max(0, Date.now() - value) : Infinity;
  }

  async function bridgeGet(path) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: 'pasi-control-center-bridge-request', method: 'GET', path },
        (response) => {
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError) { reject(new Error(runtimeError.message || 'extension messaging failed')); return; }
          if (!response || typeof response !== 'object') { reject(new Error('invalid bridge response')); return; }
          if (!response.ok) { reject(new Error('bridge request failed (' + (response.status || 0) + ')')); return; }
          try { resolve(JSON.parse(response.text || 'null')); } catch { reject(new Error('bridge returned invalid JSON')); }
        }
      );
    });
  }

  async function refreshTelemetry() {
    if (telemetryInFlight) return;
    telemetryInFlight = true;
    try {
      const [status, browser] = await Promise.all([bridgeGet('/status'), bridgeGet('/browser/observation')]);
      const { observation, data } = observationData(browser);
      const age = observationAgeMs(observation);
      const ready = data?.native_controller === true && data?.composer_present === true && data?.auth_required !== true && Number.isFinite(age) && age < 45000;
      setOverallStatus(ready ? 'ready' : data?.auth_required === true ? 'auth' : 'offline', ready ? 'READY' : data?.auth_required === true ? 'AUTH REQUIRED' : 'STALE / CHECKING');
      byId('bridge-metric').textContent = status?.service ? 'ONLINE' : 'UNKNOWN';
      byId('native-metric').textContent = data?.native_controller === true ? 'YES' : 'NO';
      byId('latency-metric').textContent = Number.isFinite(age) ? Math.round(age) + ' ms' : '—';
      byId('composer-metric').textContent = data?.composer_present === true ? 'READY' : 'NOT READY';
      byId('telemetry-updated').textContent = new Date().toLocaleTimeString();
      byId('automation-state').dataset.state = ready ? 'ready' : 'unknown';
      byId('automation-state-text').textContent = ready ? 'Browser controller is healthy. Runner commands remain desktop-owned.' : 'Runner state unavailable or browser controller is not ready.';
      byId('footer-state').textContent = ready ? 'LIVE' : 'DEGRADED';
    } catch (error) {
      setOverallStatus('offline', 'BRIDGE OFFLINE');
      byId('bridge-metric').textContent = 'OFFLINE';
      byId('native-metric').textContent = '—';
      byId('latency-metric').textContent = '—';
      byId('composer-metric').textContent = '—';
      byId('telemetry-updated').textContent = '—';
      byId('automation-state').dataset.state = 'blocked';
      byId('automation-state-text').textContent = compact(error?.message || error, 140);
      byId('footer-state').textContent = 'OFFLINE';
    } finally {
      telemetryInFlight = false;
    }
  }

  function openImportDialog() {
    const dialog = byId('import-dialog');
    byId('import-feedback').textContent = 'Structured JSON tasks can be previewed immediately. Raw text is retained for a later dissection adapter.';
    byId('roadmap-file').value = '';
    byId('roadmap-text').value = state.rawRoadmap || '';
    dialog.showModal();
  }

  async function importRoadmap() {
    const feedback = byId('import-feedback');
    const textArea = byId('roadmap-text');
    const fileInput = byId('roadmap-file');
    let raw = textArea.value.trim();
    let name = 'pasted-roadmap.txt';

    if (fileInput.files?.length) {
      const file = fileInput.files[0];
      raw = (await file.text()).trim();
      name = file.name;
    }

    if (!raw) { feedback.textContent = 'Nothing to import.'; return; }

    let parsed = null;
    try { parsed = JSON.parse(raw); } catch { parsed = null; }

    const tasks = normalizeTasks(parsed);
    state.rawRoadmap = raw;
    state.rawRoadmapName = name;
    state.tasks = tasks;
    state.preferredOrder = preferredOrderFor(tasks, []);
    state.dissection = {
      status: tasks.length ? 'structured' : 'ready',
      progress: 0,
      pass: 0,
      message: tasks.length ? 'Structured roadmap imported; awaiting planner handoff' : 'Raw roadmap imported; ready for dissection'
    };

    try { setPreferredOrder(state.preferredOrder); } catch { state.preferredOrder = tasks.map((task) => task.id); }

    await persistState();
    renderAll();
    byId('import-dialog').close();
  }

  function wireEvents() {
    byId('btn-import').addEventListener('click', openImportDialog);
    byId('btn-save-roadmap').addEventListener('click', () => { void importRoadmap(); });
    byId('btn-refresh').addEventListener('click', () => { void refreshTelemetry(); });
    byId('hardware-profile').addEventListener('change', (event) => {
      state.hardwareProfile = event.target.value;
      void persistState();
    });
  }

  async function init() {
    await loadState();
    renderAll();
    wireEvents();
    await refreshTelemetry();
    telemetryTimer = setInterval(() => { void refreshTelemetry(); }, TELEMETRY_INTERVAL_MS);
    window.addEventListener('pagehide', () => {
      if (telemetryTimer !== null) clearInterval(telemetryTimer);
    }, { once: true });
  }

  void init();

  globalThis.PASIControlCenter = {
    normalizeTasks,
    preferredOrderFor,
    orderSatisfiesDependencies,
    reorderedTaskOrder,
    observationAgeMs
  };
})();
