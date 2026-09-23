importScripts('timeout-config.js');

const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
let STALE_MS = 45 * 1000;
const CONTROLLER_LEASE_KEY = 'pasi:controller-lease';
const CONTROLLER_LEASE_MS = 10 * 1000;
let controllerClaimTail = Promise.resolve();
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
  'GET /browser/health',
  'GET /browser/state',
  'GET /browser/response',
    'POST /browser/observation',
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

async function injectExistingChatTabs() {
  if (!chrome.scripting?.executeScript) return;
  const tabs = await chrome.tabs.query({
    url: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*']
  });
  for (const tab of tabs) {
    if (typeof tab.id !== 'number') continue;
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
  const status = await bridgeJson('/status');
  const payload = await bridgeJson('/browser/observation');
  if (!status || !payload) return;
  const health = healthData(payload);
  if (!health) return;
  if (health.data.auth_required === true) return;
  if (typeof health.data.chat_url !== 'striasync function inspect() {
  await injectExistingChatTabs();

  const status = await bridgeJson('/status');
  const payload = await bridgeJson('/browser/observation');
  if (!status || !payload) return;
  const health = healthData(payload);
  if (!health || health.data.auth_required === true) return;

  const targetChatUrl = typeof health.data.chat_url === 'string'
    ? health.data.chat_url
    : '';
  if (!targetChatUrl) return;

  const tabs = await chrome.tabs.query({
    url: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*']
  });
  const matchingTab = tabs.find((tab) => sameChatConversationUrl(tab.url, targetChatUrl));
  if (matchingTab && typeof matchingTab.id === 'number') {
    try {
      await chrome.tabs.sendMessage(matchingTab.id, { type: 'pasi-health-ping' });
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
