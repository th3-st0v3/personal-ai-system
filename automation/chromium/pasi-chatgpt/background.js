const BRIDGE = 'http://127.0.0.1:8765';
const ALARM = 'pasi-watchdog';
const MAX_REFRESHES = 3;
const WINDOW_MS = 15 * 60 * 1000;
const STALE_MS = 30 * 1000;
const CREATE_RETRY_MS = 60 * 1000;

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
