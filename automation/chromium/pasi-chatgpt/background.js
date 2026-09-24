importScripts('timeout-config.js');

const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
let STALE_MS = 45 * 1000;
const CONTROLLER_LEASE_KEY = 'pasi:controller-lease';
const CONTROLLER_LEASE_MS = 10 * 1000;
const CHATGPT_ROOT_URL = 'https://chatgpt.com/';
const TAB_CREATE_COOLDOWN_KEY = 'pasi:chatgpt-tab-create-cooldown';
const TAB_CREATE_COOLDOWN_MS = 15 * 1000;
const TAB_PROVISIONING_PENDING_KEY = 'pasi:chatgpt-tab-provisioning-pending';
const RUNTIME_TELEMETRY_PENDING_KEY = 'pasi:chatgpt-runtime-telemetry-pending';
const TAB_BOOTSTRAP_RETRY_MS = 1000;
const TAB_BOOTSTRAP_READY_TTL_MS = 15 * 1000;
const MAX_RUNTIME_TELEMETRY_QUEUE = 64;
const MAX_RUNTIME_ERROR_CHARS = 2000;
let controllerClaimTail = Promise.resolve();
let tabCreateInFlight = null;
const tabBootstrapInFlight = new Map();
const tabBootstrapReadyAt = new Map();
const tabBootstrapContext = new Map();
let cachedBridgeToken = null;
let bridgeTokenPromise = null;

if (chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.warn('[PASI side panel]', error));
}

function serializeControllerClaim(task) {
  const next = controllerClaimTail.then(task, task);
  controllerClaimTail = next.catch(() => undefined);
  return next;
}

const BRIDGE_ROUTES = new Set([
  'GET /health',
  'GET /status',
  'GET /runner/capabilities',
  'GET /runner/state',
  'POST /runner/control',
  'GET /browser/observation',
  'GET /browser/provisioning',
  'GET /browser/telemetry',
  'GET /browser/health',
  'GET /browser/state',
  'GET /browser/response',
  'POST /browser/observation',
  'POST /browser/provisioning',
  'POST /browser/telemetry',
  'POST /queue',
  'POST /chat/claim',
  'POST /chat/heartbeat',
  'POST /chat/manual-reload-gate/arm',
  'POST /chat/manual-reload-gate/release',
  'POST /chat/finished',
  'POST /chat/failed',
  'POST /chat/cancel',
  'GET /next-operation'
]);
const BRIDGE_OPERATION_RE = /^\/operation\?operation_id=[^&]{1,200}$/;

async function bridgeToken(forceRefresh = false) {
  if (!forceRefresh && cachedBridgeToken) return cachedBridgeToken;
  if (bridgeTokenPromise) return bridgeTokenPromise;

  bridgeTokenPromise = (async () => {
    try {
      const response = await fetch(chrome.runtime.getURL('.bridge-token'), { cache: 'no-store' });
      if (!response.ok) return '';
      const token = (await response.text()).trim();
      if (token) cachedBridgeToken = token;
      return token;
    } catch (_) {
      return '';
    } finally {
      bridgeTokenPromise = null;
    }
  })();
  return bridgeTokenPromise;
}

function allowedBridgeRequest(method, path) {
  const normalized = String(method || 'GET').toUpperCase();
  const value = String(path || '');
  if (normalized === 'GET' && BRIDGE_OPERATION_RE.test(value)) return true;
  return BRIDGE_ROUTES.has(`${normalized} ${value}`);
}

async function bridgeFetch(path, method = 'GET', body = null, timeoutMs = 5000) {
  const normalizedMethod = String(method || 'GET').toUpperCase();
  if (!allowedBridgeRequest(normalizedMethod, path)) {
    return { ok: false, status: 400, text: '' };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const request = (token) => fetch(`${BRIDGE}${path}`, {
      method: normalizedMethod,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: 'omit',
      cache: 'no-store'
    });

    let token = await bridgeToken();
    let response = await request(token);
    if (response.status === 401) {
      cachedBridgeToken = null;
      token = await bridgeToken(true);
      if (token) response = await request(token);
    }
    return { ok: response.ok, status: response.status, text: await response.text() };
  } catch (error) {
    const message = String(error?.message || error).slice(0, 300);
    console.warn('[PASI worker bridge]', message);
    return { ok: false, status: 0, text: '', error: message };
  } finally {
    clearTimeout(timer);
  }
}

async function bridgeJson(path) {
  const response = await bridgeFetch(path);
  if (!response.ok) return null;
  try {
    return JSON.parse(response.text);
  } catch (_) {
    return null;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'pasi-controller-claim') {
    const tabId = sender?.tab?.id;
    if (typeof tabId !== 'number') {
      sendResponse({ ok: false, leader: false });
      return undefined;
    }
    serializeControllerClaim(async () => {
      const stored = await chrome.storage.local.get(CONTROLLER_LEASE_KEY);
      const current = stored?.[CONTROLLER_LEASE_KEY];
      const now = Date.now();
      const owned = current && current.tabId === tabId && now - Number(current.renewedAt || 0) < CONTROLLER_LEASE_MS;
      const available = !current || now - Number(current.renewedAt || 0) >= CONTROLLER_LEASE_MS;
      if (!owned && !available) {
        sendResponse({ ok: true, leader: false });
        return;
      }
      await chrome.storage.local.set({
        [CONTROLLER_LEASE_KEY]: { tabId, renewedAt: now }
      });
      sendResponse({ ok: true, leader: true });
    }).catch(() => sendResponse({ ok: false, leader: false }));
    return true;
  }

  if (message?.type === 'pasi-operation-received') {
    const tabId = sender?.tab?.id;
    const senderUrl = String(sender?.tab?.url || sender?.url || '');
    if (
      typeof tabId !== 'number'
      || !/^https:\/\/(?:www\.)?chatgpt\.com(?::\d+)?\//.test(senderUrl)
    ) {
      sendResponse({ ok: false, status: 403, text: 'operation receipt sender rejected' });
      return undefined;
    }
    void (async () => {
      const tabs = await listChatGptTabs();
      const selectedTab = tabs.find((tab) => tab?.id === tabId) || sender?.tab;
      await reportTabProvisioning({
        action: 'existing_tabs_no_create',
        reason: 'operation_received',
        operation_id: typeof message.operation_id === 'string' ? message.operation_id : null,
        existing_tab_count: tabs.length || 1,
        existing_tab_ids: tabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
        existing_tab_urls: tabs.map((tab) => String(tab.url || '')).filter(Boolean),
        requested_url: senderUrl,
        selected_tab_id: tabId,
        selected_tab_url: String(selectedTab?.url || senderUrl),
        selected_tab_active: selectedTab?.active === true || sender?.tab?.active === true,
        injection_ready: true,
        work_wake_sent: false
      });
    })().catch(() => {});
    sendResponse({ ok: true });
    return undefined;
  }

  if (message?.type === 'pasi-runtime-telemetry') {
    const senderUrl = String(sender?.tab?.url || sender?.url || '');
    if (
      !/^https:\/\/(?:www\.)?chatgpt\.com(?::\d+)?\//.test(senderUrl)
      && !senderUrl.startsWith(`chrome-extension://${chrome.runtime.id}/`)
    ) {
      sendResponse({ ok: false, status: 403, text: 'runtime telemetry sender rejected' });
      return undefined;
    }
    const observation = message?.observation;
    const data = observation?.data;
    if (
      !observation
      || typeof observation !== 'object'
      || observation?.schema_version !== 'pasi-native-chromium-v2'
      || !data
      || data.kind !== 'chatgpt_runtime_telemetry'
    ) {
      sendResponse({ ok: false, status: 400, text: 'invalid runtime telemetry observation' });
      return undefined;
    }
    void queueRuntimeTelemetry(observation).then(() => flushRuntimeTelemetry());
    sendResponse({ ok: true });
    return undefined;
  }

  if (message?.type === 'pasi-control-center-bridge-request') {
    const senderUrl = String(sender?.url || '');
    const extensionPrefix = `chrome-extension://${chrome.runtime.id}/`;
    if (!senderUrl.startsWith(extensionPrefix)) {
      console.warn('[PASI control-center bridge] rejected non-extension sender', senderUrl.slice(0, 200));
      sendResponse({ ok: false, status: 403, text: 'control-center sender rejected' });
      return undefined;
    }

    const method = String(message.method || 'GET').toUpperCase();
    const path = String(message.path || '');
    const allowed = (
      (method === 'GET' && new Set(['/status', '/browser/observation', '/browser/provisioning', '/runner/capabilities', '/runner/state']).has(path))
      || (method === 'POST' && path === '/runner/control')
    );
    if (!allowed) {
      console.warn('[PASI control-center bridge] rejected route', method, path);
      sendResponse({ ok: false, status: 403, text: 'control-center route rejected' });
      return undefined;
    }

    bridgeFetch(path, method, message.body ?? null, 5000).then(sendResponse);
    return true;
  }

  if (!message || message.type !== 'pasi-bridge-request') return undefined;
  const senderUrl = String(sender?.tab?.url || sender?.url || '');
  if (!/^https:\/\/(?:www\.)?chatgpt\.com(?::\d+)?\//.test(senderUrl)) {
    console.warn('[PASI worker bridge] rejected non-ChatGPT sender', senderUrl.slice(0, 200));
    sendResponse({ ok: false, status: 403, text: 'ChatGPT sender rejected' });
    return undefined;
  }

  const method = String(message.method || 'GET').toUpperCase();
  const path = String(message.path || '');
  if (!allowedBridgeRequest(method, path)) {
    sendResponse({ ok: false, status: 403, text: '' });
    return undefined;
  }

  const body = message.body == null ? null : message.body;
  if (body !== null && (typeof body !== 'object' || Array.isArray(body))) {
    sendResponse({ ok: false, status: 400, text: '' });
    return undefined;
  }

  const requestedTimeout = Number(message.timeout);
  const timeoutMs = Number.isFinite(requestedTimeout)
    ? Math.min(Math.max(requestedTimeout, 250), 10000)
    : 10000;
  bridgeFetch(path, method, body, timeoutMs).then(sendResponse);
  return true;
});
function observationAge(observation) {
  const stamp = observation && observation.captured_at;
  if (typeof stamp !== 'string') return Infinity;
  const value = Date.parse(stamp);
  if (!Number.isFinite(value)) return Infinity;
  return Math.max(0, Date.now() - value);
}

function healthData(payload) {
  const observation = payload && payload.observation;
  if (!observation || typeof observation !== 'object') return null;
  const data = observation.data && typeof observation.data === 'object' ? observation.data : observation;
  return { observation, data };
}

function sameChatConversationUrl(candidate, target) {
  try {
    const left = new URL(String(candidate || ''));
    const right = new URL(String(target || ''));
    const allowedOrigins = new Set(['https://chatgpt.com', 'https://www.chatgpt.com']);
    return allowedOrigins.has(left.origin)
      && allowedOrigins.has(right.origin)
      && left.pathname === right.pathname
      && left.pathname.startsWith('/c/');
  } catch (_) {
    return false;
  }
}

async function listChatGptTabs() {
  return chrome.tabs.query({
    url: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*']
  });
}

async function reportTabProvisioning(event) {
  const observation = {
    schema_version: 'pasi-native-chromium-v2',
    captured_at: new Date().toISOString(),
    data: {
      kind: 'chatgpt_tab_provisioning',
      ...event
    }
  };
  try {
    await chrome.storage.local.set({ [TAB_PROVISIONING_PENDING_KEY]: observation });
  } catch (_) {
    // Local persistence is best-effort; the bridge post below remains the primary path.
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await bridgeFetch('/browser/provisioning', 'POST', { observation }, 2000);
      if (response.ok) {
        try {
          await chrome.storage.local.remove(TAB_PROVISIONING_PENDING_KEY);
        } catch (_) {}
        return true;
      }
    } catch (_) {
      // Retry transient bridge/service-worker failures without blocking tab recovery.
    }
    if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  return false;
}


let runtimeTelemetryFlushInFlight = null;
let runtimeTelemetryQueueTail = Promise.resolve();

function runtimeErrorText(error) {
  return String(error?.message || error || 'unknown runtime error').slice(0, MAX_RUNTIME_ERROR_CHARS);
}

function queueRuntimeTelemetry(observation) {
  const task = runtimeTelemetryQueueTail.then(async () => {
    try {
      const stored = await chrome.storage.local.get(RUNTIME_TELEMETRY_PENDING_KEY);
      const queue = Array.isArray(stored?.[RUNTIME_TELEMETRY_PENDING_KEY])
        ? stored[RUNTIME_TELEMETRY_PENDING_KEY]
        : [];
      queue.push(observation);
      await chrome.storage.local.set({
        [RUNTIME_TELEMETRY_PENDING_KEY]: queue.slice(-MAX_RUNTIME_TELEMETRY_QUEUE)
      });
    } catch (_) {}
  });
  runtimeTelemetryQueueTail = task.catch(() => undefined);
  return task;
}

async function flushRuntimeTelemetry() {
  if (runtimeTelemetryFlushInFlight) return runtimeTelemetryFlushInFlight;
  runtimeTelemetryFlushInFlight = (async () => {
    try {
      const stored = await chrome.storage.local.get(RUNTIME_TELEMETRY_PENDING_KEY);
      const queue = Array.isArray(stored?.[RUNTIME_TELEMETRY_PENDING_KEY])
        ? stored[RUNTIME_TELEMETRY_PENDING_KEY].slice()
        : [];
      while (queue.length) {
        const response = await bridgeFetch('/browser/telemetry', 'POST', { observation: queue[0] }, 2000);
        if (!response.ok) break;
        queue.shift();
        await chrome.storage.local.set({
          [RUNTIME_TELEMETRY_PENDING_KEY]: queue
        });
      }
      return queue.length === 0;
    } catch (_) {
      return false;
    } finally {
      runtimeTelemetryFlushInFlight = null;
    }
  })();
  return runtimeTelemetryFlushInFlight;
}

function reportRuntimeTelemetry(event) {
  const observation = {
    schema_version: 'pasi-native-chromium-v2',
    captured_at: new Date().toISOString(),
    data: {
      kind: 'chatgpt_runtime_telemetry',
      ...event
    }
  };
  void queueRuntimeTelemetry(observation).then(() => flushRuntimeTelemetry());
  return observation;
}

async function flushPendingTabProvisioning() {
  try {
    const stored = await chrome.storage.local.get(TAB_PROVISIONING_PENDING_KEY);
    const observation = stored?.[TAB_PROVISIONING_PENDING_KEY];
    if (!observation || typeof observation !== 'object') return false;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const response = await bridgeFetch('/browser/provisioning', 'POST', { observation }, 2000);
      if (response.ok) {
        await chrome.storage.local.remove(TAB_PROVISIONING_PENDING_KEY);
        return true;
      }
      if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
    }
  } catch (_) {}
  return false;
}

function validChatConversationUrl(value) {
  return sameChatConversationUrl(value, value) ? String(value) : '';
}

function bridgeHasPendingWork(status, health) {
  if (health?.data?.active_operation_id) return true;
  const queueSize = Number(status?.queue_size);
  if (Number.isFinite(queueSize) && queueSize > 0) return true;
  const counts = status?.counts && typeof status.counts === 'object' ? status.counts : {};
  return ['queued', 'claimed', 'generating', 'running'].some((key) => {
    const value = Number(counts[key]);
    return Number.isFinite(value) && value > 0;
  });
}

function selectChatGptTab(tabs, targetChatUrl) {
  const candidates = Array.isArray(tabs) ? tabs.filter((tab) => tab && typeof tab === 'object') : [];
  const exact = validChatConversationUrl(targetChatUrl)
    ? candidates.filter((tab) => sameChatConversationUrl(tab?.url, targetChatUrl))
    : [];
  return (
    exact.find((tab) => tab.active === true)
    || exact[0]
    || candidates.find((tab) => tab.active === true)
    || candidates[0]
    || null
  );
}

async function ensureChatGptTab(targetChatUrl, pendingWork, resumeOperationId = null) {
  if (!pendingWork) return null;
  const existingTabs = await listChatGptTabs();
  if (existingTabs.length > 0) {
    const selectedTab = selectChatGptTab(existingTabs, targetChatUrl);
    const selectedTabId = typeof selectedTab?.id === 'number' ? selectedTab.id : null;
    const injectionReady = selectedTabId !== null
      ? await injectChatGptTab(selectedTabId, { source: 'existing_tab_pending_work' })
      : false;
    let workWakeSent = false;
    if (selectedTabId !== null && injectionReady) {
      if (injectionReady) {
        try {
          await chrome.tabs.sendMessage(selectedTabId, { type: 'pasi-work-wake' });
          workWakeSent = true;
        } catch (_) {
          workWakeSent = false;
        }
      }
    }
    void reportTabProvisioning({
      action: 'existing_tabs_no_create',
      existing_tab_count: existingTabs.length,
      existing_tab_ids: existingTabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
      existing_tab_urls: existingTabs.map((tab) => String(tab.url || '')).filter(Boolean),
      requested_url: validChatConversationUrl(targetChatUrl) || CHATGPT_ROOT_URL,
      selected_tab_id: selectedTabId,
      selected_tab_url: String(selectedTab?.url || ''),
      selected_tab_active: selectedTab?.active === true,
      injection_ready: injectionReady,
      work_wake_sent: workWakeSent
    });
    return injectionReady ? selectedTabId : null;
  }
  if (tabCreateInFlight) {
    void reportTabProvisioning({
      action: 'in_flight_no_create',
      existing_tab_count: 0,
      requested_url: validChatConversationUrl(targetChatUrl) || CHATGPT_ROOT_URL
    });
    return tabCreateInFlight;
  }

  const requestedUrl = validChatConversationUrl(targetChatUrl) || CHATGPT_ROOT_URL;
  tabCreateInFlight = (async () => {
    try {
      const stored = await chrome.storage.local.get(TAB_CREATE_COOLDOWN_KEY);
      const attemptedAt = Number(stored?.[TAB_CREATE_COOLDOWN_KEY]?.attempted_at || 0);
      if (attemptedAt > 0 && Date.now() - attemptedAt < TAB_CREATE_COOLDOWN_MS) {
        void reportTabProvisioning({
          action: 'cooldown_no_create',
          existing_tab_count: 0,
          requested_url: requestedUrl,
          cooldown_age_ms: Date.now() - attemptedAt
        });
        return null;
      }

      // Re-check immediately before creation so two watchdog passes cannot race
      // between the first tab query and chrome.tabs.create().
      const currentTabs = await listChatGptTabs();
      if (currentTabs.length > 0) {
        void reportTabProvisioning({
          action: 'race_existing_tabs_no_create',
          existing_tab_count: currentTabs.length,
          existing_tab_ids: currentTabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
          existing_tab_urls: currentTabs.map((tab) => String(tab.url || '')).filter(Boolean),
          requested_url: requestedUrl
        });
        return null;
      }

      const attemptedAtMs = Date.now();
      await chrome.storage.local.set({
        [TAB_CREATE_COOLDOWN_KEY]: {
          attempted_at: attemptedAtMs,
          url: requestedUrl
        }
      });
      const created = await chrome.tabs.create({ url: requestedUrl, active: false });
      const afterCreateTabs = await listChatGptTabs();
      const createdTabId = typeof created?.id === 'number' ? created.id : null;
      const effectiveResumeOperationId = typeof resumeOperationId === 'string' && resumeOperationId
        ? resumeOperationId
        : null;
      if (createdTabId !== null) {
        const bootstrapContext = {
          requestedUrl,
          attemptedAtMs,
          afterCreateTabs,
          resumeOperationId: effectiveResumeOperationId
        };
        tabBootstrapContext.set(createdTabId, bootstrapContext);
        void reportTabProvisioning({
          action: 'created_pending_bootstrap',
          existing_tab_count: 0,
          requested_url: requestedUrl,
          created_tab_id: createdTabId,
          created_tab_url: String(created?.url || ''),
          after_create_tab_count: afterCreateTabs.length,
          after_create_tab_ids: afterCreateTabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
          after_create_tab_urls: afterCreateTabs.map((tab) => String(tab.url || '')).filter(Boolean),
          cooldown_started_at: attemptedAtMs,
          injection_ready: false,
          resume_operation_id: effectiveResumeOperationId,
          resume_handoff_sent: false
        });
        void bootstrapCreatedChatGptTab(createdTabId, bootstrapContext);
      }
      return createdTabId;
    } catch (error) {
      void reportTabProvisioning({
        action: 'create_error',
        existing_tab_count: 0,
        requested_url: requestedUrl,
        error: String(error?.message || error).slice(0, 300)
      });
      console.warn('[PASI tab provisioning]', String(error?.message || error));
      return null;
    } finally {
      tabCreateInFlight = null;
    }
  })();
  return tabCreateInFlight;
}

let injectExistingTabsInFlight = null;

async function injectChatGptTab(tabId, context = {}) {
  if (!chrome.scripting?.executeScript || typeof tabId !== 'number') {
    const error = 'PASI_RUNTIME: scripting.executeScript unavailable or tab id invalid';
    reportRuntimeTelemetry({
      event: 'INJECTION_FAILURE',
      status: 'failure',
      tab_id: tabId,
      source: context.source || 'unknown',
      error
    });
    return false;
  }

  try {
    await chrome.tabs.sendMessage(tabId, { type: 'pasi-health-ping' });
    reportRuntimeTelemetry({
      event: 'INJECTION_SUCCESS',
      status: 'success',
      tab_id: tabId,
      source: context.source || 'unknown',
      mode: 'existing_controller'
    });
    return true;
  } catch (error) {
    // No live controller listener is present; inject into the existing tab.
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        try {
          const handle = globalThis.__PASI_NATIVE_CONTROLLER_HANDLE__;
          if (handle && typeof handle.stop === 'function') handle.stop();
        } catch (_) {}
        try {
          const handle = globalThis.__PASI_NATIVE_RECOVERY_HANDLE__;
          if (handle && typeof handle.stop === 'function') handle.stop();
        } catch (_) {}
        delete globalThis.__PASI_NATIVE_CONTROLLER_HANDLE__;
        delete globalThis.__PASI_NATIVE_CONTROLLER_STARTED__;
        delete globalThis.__PASI_NATIVE_RECOVERY_HANDLE__;
        delete globalThis.__PASI_NATIVE_RECOVERY_STARTED__;
      }
    });

    await chrome.scripting.executeScript({
      target: { tabId },
      files: [
        'timeout-config.js',
        'detectors.js',
        'recovery_progress.js',
        'content.js',
        'recovery.js'
      ]
    });
    await chrome.tabs.sendMessage(tabId, { type: 'pasi-health-ping' });
    reportRuntimeTelemetry({
      event: 'INJECTION_SUCCESS',
      status: 'success',
      tab_id: tabId,
      source: context.source || 'unknown',
      mode: 'execute_script'
    });
    return true;
  } catch (error) {
    reportRuntimeTelemetry({
      event: 'INJECTION_FAILURE',
      status: 'failure',
      tab_id: tabId,
      source: context.source || 'unknown',
      mode: 'execute_script',
      error: runtimeErrorText(error)
    });
    return false;
  }
}

async function bootstrapCreatedChatGptTab(tabId, context = {}) {
  if (typeof tabId !== 'number') return false;
  const readyAt = Number(tabBootstrapReadyAt.get(tabId) || 0);
  if (readyAt > 0 && Date.now() - readyAt < TAB_BOOTSTRAP_READY_TTL_MS) {
    return true;
  }
  const existing = tabBootstrapInFlight.get(tabId);
  if (existing) return existing;

  const run = (async () => {
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    reportRuntimeTelemetry({
      event: 'BOOTSTRAP_ATTEMPT',
      status: 'started',
      tab_id: tabId,
      source: 'created_tab',
      attempt,
      max_attempts: 10
    });
    const ok = await injectChatGptTab(tabId, { source: 'created_tab' });
    if (ok) {
      let resumeHandoffSent = false;
      const trackProvisioning = (
        typeof context.requestedUrl === 'string' ||
        typeof context.resumeOperationId === 'string'
      );
      const resumeOperationId = typeof context.resumeOperationId === 'string' && context.resumeOperationId
        ? context.resumeOperationId
        : null;
      if (resumeOperationId) {
        try {
          const response = await chrome.tabs.sendMessage(tabId, {
            type: 'pasi-resume-operation',
            operation_id: resumeOperationId
          });
          resumeHandoffSent = response?.ok === true;
        } catch (_) {
          resumeHandoffSent = false;
        }
      }
      if (trackProvisioning) {
        void reportTabProvisioning({
        action: 'created',
        existing_tab_count: 0,
        requested_url: String(context.requestedUrl || ''),
        created_tab_id: tabId,
        after_create_tab_count: Number(context.afterCreateTabs?.length || 1),
        after_create_tab_ids: Array.isArray(context.afterCreateTabs)
          ? context.afterCreateTabs.map((tab) => tab.id).filter((id) => typeof id === 'number')
          : [tabId],
        after_create_tab_urls: Array.isArray(context.afterCreateTabs)
          ? context.afterCreateTabs.map((tab) => String(tab.url || '')).filter(Boolean)
          : [],
        cooldown_started_at: Number(context.attemptedAtMs || 0),
        injection_ready: true,
        resume_operation_id: resumeOperationId,
        resume_handoff_sent: resumeHandoffSent
        });
      }
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, TAB_BOOTSTRAP_RETRY_MS));
  }
  reportRuntimeTelemetry({
    event: 'INJECTION_FAILURE',
    status: 'failure',
    tab_id: tabId,
    source: 'created_tab',
    phase: 'bootstrap_exhausted',
    error: 'PASI_RUNTIME: created-tab bootstrap exhausted all injection attempts'
  });
  if (typeof context.requestedUrl === 'string' || typeof context.resumeOperationId === 'string') {
    void reportTabProvisioning({
    action: 'create_bootstrap_failed',
    existing_tab_count: 0,
    requested_url: String(context.requestedUrl || ''),
    created_tab_id: tabId,
    injection_ready: false,
    resume_operation_id: typeof context.resumeOperationId === 'string' ? context.resumeOperationId : null,
    resume_handoff_sent: false
    });
  }
  return false;
  })();

  tabBootstrapInFlight.set(tabId, run);
  try {
    const result = await run;
    if (result === true) tabBootstrapReadyAt.set(tabId, Date.now());
    return result;
  } finally {
    if (tabBootstrapInFlight.get(tabId) === run) {
      tabBootstrapInFlight.delete(tabId);
    }
    if (tabBootstrapContext.get(tabId) === context) {
      tabBootstrapContext.delete(tabId);
    }
  }
}

async function injectExistingChatTabs() {
  if (!chrome.scripting?.executeScript) return;
  if (injectExistingTabsInFlight) return injectExistingTabsInFlight;

  const run = (async () => {
    const tabs = await listChatGptTabs();
    for (const tab of tabs) {
      if (typeof tab.id !== 'number') continue;
      await injectChatGptTab(tab.id, { source: 'watchdog_existing_tab' });
    }
  })();

  injectExistingTabsInFlight = run;
  try {
    await run;
  } finally {
    if (injectExistingTabsInFlight === run) {
      injectExistingTabsInFlight = null;
    }
  }
}
async function inspect() {
  await flushRuntimeTelemetry();
  await flushPendingTabProvisioning();
  await injectExistingChatTabs();

  const status = await bridgeJson('/status');
  const payload = await bridgeJson('/browser/observation');
  if (!status) return;
  const health = healthData(payload);
  const liveHealth = (
    health &&
    observationAge(health.observation) <= STALE_MS
  ) ? health : null;
  const targetChatUrl = (
    typeof liveHealth?.data?.chat_url === 'string'
  ) ? liveHealth.data.chat_url : '';
  const pendingWork = bridgeHasPendingWork(status, liveHealth);

  let resumeOperationId = typeof liveHealth?.data?.active_operation_id === 'string'
    ? liveHealth.data.active_operation_id
    : null;
  if (!resumeOperationId && pendingWork) {
    const browserState = await bridgeJson('/browser/state');
    const stateData = browserState?.data;
    if (typeof stateData?.active_operation_id === 'string') {
      resumeOperationId = stateData.active_operation_id;
    }
  }
  if (!resumeOperationId && pendingWork) {
    const browserResponse = await bridgeJson('/browser/response');
    const responseData = browserResponse?.data;
    if (typeof responseData?.active_operation_id === 'string') {
      resumeOperationId = responseData.active_operation_id;
    }
  }
  const createdTabId = await ensureChatGptTab(targetChatUrl, pendingWork, resumeOperationId);
  if (createdTabId !== null) return;
  if (!health) return;

  const tabs = await listChatGptTabs();
  const matchingTab = targetChatUrl
    ? tabs.find((tab) => sameChatConversationUrl(tab.url, targetChatUrl))
    : null;
  const fallbackTab = matchingTab || tabs[0];
  if (fallbackTab && typeof fallbackTab.id === 'number') {
    try {
      await chrome.tabs.sendMessage(fallbackTab.id, { type: 'pasi-health-ping' });
    } catch (_) {
      // Existing-tab injection will be retried on the next watchdog pass.
    }
  }
}

async function applyTimeoutPolicy() {
  try {
    const response = await fetch(chrome.runtime.getURL('timeout-policy.json'), { cache: 'no-store' });
    if (!response.ok) return;
    const policy = await response.json();
    const staleSeconds = Number(policy?.stale_seconds);
    if (Number.isFinite(staleSeconds) && staleSeconds > 0) {
      STALE_MS = staleSeconds * 1000;
    }
  } catch (_) {}
}

async function ensureWatchdogAlarm() {
  await applyTimeoutPolicy();
  try {
    const alarm = await chrome.alarms.get(ALARM);
    const period = Number(alarm?.periodInMinutes);
    if (!alarm || !Number.isFinite(period) || Math.abs(period - 0.5) > 0.001) {
      await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
    }
  } catch (_) {}
}

chrome.runtime.onInstalled.addListener(() => {
  void ensureWatchdogAlarm();
  void injectExistingChatTabs();
  void inspect();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureWatchdogAlarm();
  void injectExistingChatTabs();
  void inspect();
});

void ensureWatchdogAlarm();
void injectExistingChatTabs();
void inspect();

if (chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.warn('[PASI side panel]', error));
}


chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) inspect();
});


chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  const url = String(tab?.url || '');
  if (!/^https:\/\/(?:www\.)?chatgpt\.com\//.test(url)) return;
  void bootstrapCreatedChatGptTab(tabId, tabBootstrapContext.get(tabId) || {});
});
