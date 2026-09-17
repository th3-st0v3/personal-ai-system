const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
const MAX_REFRESHES = 3;
const WINDOW_MS = 15 * 60 * 1000;
const STALE_MS = 30 * 1000;

async function bridgeJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(`${BRIDGE}${path}`, { signal: controller.signal });
    if (!response.ok) return null;
    return await response.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

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

async function inspect() {
  const status = await bridgeJson('/status');
  const payload = await bridgeJson('/browser/observation');
  if (!status || !payload || !status.queue_size) return;
  const health = healthData(payload);
  if (!health) return;
  if (health.data.auth_required === true) return;
  if (observationAge(health.observation) <= STALE_MS) return;

  const tabs = await chrome.tabs.query({ url: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*'] });
  if (!tabs.length) return;
  tabs.sort((a, b) => Number(b.lastAccessed || 0) - Number(a.lastAccessed || 0));
  const tab = tabs[0];
  if (!tab.id) return;

  const budget = await refreshBudget(tab.id);
  if (budget.count >= MAX_REFRESHES) return;
  budget.count += 1;
  await chrome.storage.local.set({ [`refresh:${tab.id}`]: budget });
  await chrome.tabs.reload(tab.id);
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
