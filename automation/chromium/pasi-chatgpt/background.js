const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
const MAX_REFRESHES = 3;
const WINDOW_MS = 15 * 60 * 1000;
const STALE_MS = 30 * 1000;
const CREATE_RETRY_MS = 60 * 1000;
const CONTROLLER_LEASE_KEY = 'pasi:controller-lease';
const CONTROLLER_LEASE_MS = 10 * 1000;

const BRIDGE_ROUTES = new Set([
  'GET /health',
  'GET /status',
  'GET /browser/observation',
  'GET /browser/response',
  'POST /next-operation',
  'POST /browser/observation',
  'POST /queue',
  'POST /chat/claim',
  'POST /chat/heartbeat',
  'POST /chat/finished',
  'POST /chat/failed',
  'POST /chat/cancel'
]);
const BRIDGE_OPERATION_RE = /^\/operation\?operation_id=[^&]{1,200}$/;

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
    const response = await fetch(`${BRIDGE}${path}`, {
      method: normalizedMethod,
      headers: body ? { 'Content-Type': 'text/plain;charset=UTF-8' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: 'omit',
      cache: 'no-store'
    });
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
    chrome.storage.local.get(CONTROLLER_LEASE_KEY).then((stored) => {
      const current = stored?.[CONTROLLER_LEASE_KEY];
      const now = Date.now();
      const owned = current && current.tabId === tabId && now - Number(current.renewedAt || 0) < CONTROLLER_LEASE_MS;
      const available = !current || now - Number(current.renewedAt || 0) >= CONTROLLER_LEASE_MS;
      if (!owned && !available) {
        sendResponse({ ok: true, leader: false });
        return;
      }
      return chrome.storage.local.set({
        [CONTROLLER_LEASE_KEY]: { tabId, renewedAt: now }
      }).then(() => sendResponse({ ok: true, leader: true }));
    }).catch(() => sendResponse({ ok: false, leader: false }));
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

  bridgeFetch(path, method, body, 10000).then(sendResponse);
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

async function refreshBudget(tabId) {
  const key = `refresh:${tabId}`;
  const stored = (await chrome.storage.local.get(key))[key] || { startedAt: Date.now(), count: 0 };
  if (Date.now() - stored.startedAt > WINDOW_MS) return { startedAt: Date.now(), count: 0 };
  return stored;
}

async function createCooldown(targetChatUrl) {
  const key = `create:${targetChatUrl}`;
  const stored = (await chrome.storage.local.get(key))[key];
  if (!stored || Date.now() - stored > CREATE_RETRY_MS) return false;
  return true;
}

async function markCreateAttempt(targetChatUrl) {
  await chrome.storage.local.set({ [`create:${targetChatUrl}`]: Date.now() });
}

async function reloadBoundedTab(tab) {
  if (!tab || typeof tab.id !== 'number') return;

  const budget = await refreshBudget(tab.id);
  if (budget.count >= MAX_REFRESHES) return;
  budget.count += 1;
  await chrome.storage.local.set({ [`refresh:${tab.id}`]: budget });
  await chrome.tabs.reload(tab.id);
}

async function inspect() {
  const status = await bridgeJson('/status');
  const payload = await bridgeJson('/browser/observation');
  if (!status || !payload) return;
  const health = healthData(payload);
  if (!health) return;
  if (health.data.auth_required === true) return;
  if (typeof health.data.active_operation_id !== 'string' || !health.data.active_operation_id.trim()) return;
  if (typeof health.data.chat_url !== 'string' || !health.data.chat_url.trim()) return;
  if (observationAge(health.observation) <= STALE_MS) return;

  const tabs = await chrome.tabs.query({ url: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*'] });
  const targetChatUrl = typeof health.data.chat_url === 'string' ? health.data.chat_url : '';
  const matchingTab = targetChatUrl
    ? tabs.find((tab) => tab.url === targetChatUrl)
    : null;
  // If the exact conversation tab is gone, recreate only the verified target
  // URL. Never substitute another ChatGPT tab, which could belong to a separate task.
  if (!matchingTab) {
    if (await createCooldown(targetChatUrl)) return;
    await markCreateAttempt(targetChatUrl);
    try {
      await chrome.tabs.create({ url: targetChatUrl });
    } catch (_) {
      // Keep the cooldown so a transient browser rejection does not create
      // repeated tabs on every watchdog alarm.
    }
    return;
  }
  await chrome.storage.local.remove(`create:${targetChatUrl}`);
  await reloadBoundedTab(matchingTab);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) inspect();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.local.remove(`refresh:${tabId}`);
});
