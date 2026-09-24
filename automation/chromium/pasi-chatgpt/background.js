importScripts('timeout-config.js');

const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
let STALE_MS = 45 * 1000;
const CONTROLLER_LEASE_KEY = 'pasi:controller-lease';
const CONTROLLER_LEASE_MS = 10 * 1000;
const CHATGPT_ROOT_URL = 'https://chatgpt.com/';
const TAB_CREATE_COOLDOWN_KEY = 'pasi:chatgpt-tab-create-cooldown';
const TAB_CREATE_COOLDOWN_MS = 15 * 1000;
let controllerClaimTail = Promise.resolve();
let tabCreateInFlight = null;
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
  'GET /browser/health',
  'GET /browser/state',
  'GET /browser/response',
  'POST /browser/observation',
  'POST /browser/provisioning',
  'POST /queue',
  'POST /chat/claim',
  'POST /chat/heartbeat',
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

  if (message?.type === 'pasi-control-center-bridge-request') {
    const senderUrl = String(sender?.url || '');
    const extensionPrefix = `chrome-extension://${chrome.runtime.id}/`;
    if (!senderUrl.startsWith(extensionPrefix)) {
      sendResponse({ ok: false, status: 403, text: '' });
      return undefined;
    }

    const method = String(message.method || 'GET').toUpperCase();
    const path = String(message.path || '');
    const allowed = (
      (method === 'GET' && new Set(['/status', '/browser/observation', '/runner/capabilities', '/runner/state']).has(path))
      || (method === 'POST' && path === '/runner/control')
    );
    if (!allowed) {
      sendResponse({ ok: false, status: 403, text: '' });
      return undefined;
    }

    bridgeFetch(path, method, message.body ?? null, 5000).then(sendResponse);
    return true;
  }

  if (!message || message.type !== 'pasi-bridge-request') return undefined;
  const senderUrl = String(sender?.url || '');
  if (!/^https:\/\/(?:www\.)?chatgpt\.com(?::\d+)?\//.test(senderUrl)) {
    sendResponse({ ok: false, status: 403, text: '' });
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
  try {
    await bridgeFetch('/browser/provisioning', 'POST', {
      schema_version: 'pasi-native-chromium-v2',
      captured_at: new Date().toISOString(),
      data: {
        kind: 'chatgpt_tab_provisioning',
        ...event
      }
    }, 2000);
  } catch (_) {
    // Provisioning telemetry must never block recovery.
  }
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

async function ensureChatGptTab(targetChatUrl, pendingWork) {
  if (!pendingWork) return null;
  const existingTabs = await listChatGptTabs();
  if (existingTabs.length > 0) {
    void reportTabProvisioning({
      action: 'existing_tabs_no_create',
      existing_tab_count: existingTabs.length,
      existing_tab_ids: existingTabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
      existing_tab_urls: existingTabs.map((tab) => String(tab.url || '')).filter(Boolean),
      requested_url: validChatConversationUrl(targetChatUrl) || CHATGPT_ROOT_URL
    });
    return null;
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
      void reportTabProvisioning({
        action: 'created',
        existing_tab_count: 0,
        requested_url: requestedUrl,
        created_tab_id: typeof created?.id === 'number' ? created.id : null,
        created_tab_url: String(created?.url || ''),
        after_create_tab_count: afterCreateTabs.length,
        after_create_tab_ids: afterCreateTabs.map((tab) => tab.id).filter((id) => typeof id === 'number'),
        after_create_tab_urls: afterCreateTabs.map((tab) => String(tab.url || '')).filter(Boolean),
        cooldown_started_at: attemptedAtMs
      });
      return typeof created?.id === 'number' ? created.id : null;
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

async function injectExistingChatTabs() {
  if (!chrome.scripting?.executeScript) return;
  const tabs = await listChatGptTabs();
  for (const tab of tabs) {
    if (typeof tab.id !== 'number') continue;

    // A previously injected controller can answer this ping. Do not
    // re-execute the full support-script bundle on an already-live tab,
    // because the support scripts are intentionally global and are not
    // themselves controller lifecycle owners.
    try {
      await chrome.tabs.sendMessage(tab.id, { type: 'pasi-health-ping' });
      continue;
    } catch (_) {
      // No live controller listener is present; inject into the existing tab.
    }

    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: [
          'timeout-config.js',
          'detectors.js',
          'recovery_progress.js',
          'content.js',
          'recovery.js'
        ]
      });
    } catch (_) {
      // Retry later without creating, navigating, or reloading a tab.
    }
  }
}
async function inspect() {
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

  const createdTabId = await ensureChatGptTab(targetChatUrl, pendingWork);
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
});

chrome.runtime.onStartup.addListener(() => {
  void ensureWatchdogAlarm();
  void injectExistingChatTabs();
});

void ensureWatchdogAlarm();
void injectExistingChatTabs();

if (chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.warn('[PASI side panel]', error));
}


chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) inspect();
});
