/* global chrome */
'use strict';

const STORAGE_KEY = 'pasi:userscripts:v1';
const MAIN_BRIDGE_ID = 'pasi-userscript-main-bridge';
const MAX_SOURCE_CHARS = 2_000_000;
const MAX_RPC_BODY_CHARS = 5_000_000;
const MAX_VALUES = 10_000;
const GRANT_ALIASES = new Map([
  ['GM.getValue', 'storage'],
  ['GM_setValue', 'storage'],
  ['GM_getValue', 'storage'],
  ['GM_deleteValue', 'storage'],
  ['GM_listValues', 'storage'],
  ['GM_fetch', 'fetch'],
  ['GM_xmlhttpRequest', 'xmlhttprequest'],
  ['GM_webRequest', 'webRequest'],
  ['GM_registerMenuCommand', 'menu'],
  ['GM_unregisterMenuCommand', 'menu'],
  ['GM_notification', 'notifications'],
  ['GM_download', 'downloads'],
  ['GM_openInTab', 'tabs'],
  ['GM_setClipboard', 'clipboard'],
  ['unsafeWindow', 'unsafeWindow'],
]);

let mutationTail = Promise.resolve();

function serializeMutation(task) {
  const next = mutationTail.then(task, task);
  mutationTail = next.catch(() => undefined);
  return next;
}

function apiAvailable() {
  return Boolean(
    globalThis.chrome &&
    chrome.userScripts &&
    typeof chrome.userScripts.getScripts === 'function'
  );
}

function extensionContextAlive() {
  try {
    return Boolean(chrome.runtime?.id);
  } catch (_) {
    return false;
  }
}

async function withContextRecovery(task, retries = 1) {
  let attempt = 0;
  while (true) {
    if (!extensionContextAlive()) {
      if (attempt >= retries) throw new Error('Extension context invalidated');
      await new Promise((resolve) => setTimeout(resolve, 50));
      attempt += 1;
      continue;
    }
    try {
      return await task();
    } catch (error) {
      const message = String(error?.message || error);
      if (!/context invalidated|extension context|receiving end|disconnected/i.test(message) || attempt >= retries) {
        throw error;
      }
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
}

function parseMetadata(source) {
  if (typeof source !== 'string' || source.length > MAX_SOURCE_CHARS) {
    throw new Error('userscript source is missing or exceeds the 2 MiB limit');
  }
  const match = source.match(/(?:\/\/|\/*)\s*==UserScript==([\s\S]*?)(?:\/\/|\/*)\s*==\/UserScript==/i);
  if (!match) throw new Error('userscript metadata block not found');
  const metadata = {
    name: 'Untitled userscript',
    namespace: 'pasi',
    version: '0.0.0',
    description: '',
    matches: [],
    includeGlobs: [],
    excludeMatches: [],
    excludeGlobs: [],
    grants: [],
    connects: [],
    runAt: 'document_idle',
    allFrames: false,
    world: 'USER_SCRIPT',
  };
  for (const line of match[1].split(/\r?\n/)) {
    const clean = line.replace(/^\s*\/\*\*?|\*\/\s*$/g, '').trim();
    const item = clean.match(/^@([A-Za-z][\w-]*)(?:\s+(.+?))?$/);
    if (!item) continue;
    const key = item[1].toLowerCase();
    const value = (item[2] || '').trim();
    if (key === 'name' && value) metadata.name = value;
    else if (key === 'namespace' && value) metadata.namespace = value;
    else if (key === 'version' && value) metadata.version = value;
    else if (key === 'description') metadata.description = value;
    else if (key === 'match' && value) metadata.matches.push(value);
    else if (key === 'include' && value) metadata.includeGlobs.push(value);
    else if (key === 'exclude-match' && value) metadata.excludeMatches.push(value);
    else if (key === 'exclude' && value) metadata.excludeGlobs.push(value);
    else if (key === 'grant' && value && value !== 'none') metadata.grants.push(value);
    else if (key === 'connect' && value) metadata.connects.push(value);
    else if (key === 'run-at' && ['document_start', 'document_end', 'document_idle'].includes(value)) metadata.runAt = value;
    else if (key === 'all-frames') metadata.allFrames = value !== 'false';
    else if (key === 'world' && value.toUpperCase() === 'MAIN') metadata.world = 'MAIN';
    else if (key === 'unsafe-window') metadata.world = 'MAIN';
  }
  if (!metadata.matches.length) throw new Error('userscript must declare at least one @match');
  if (metadata.world === 'MAIN' && !metadata.grants.includes('unsafeWindow')) {
    metadata.grants.push('unsafeWindow');
  }
  metadata.grants = [...new Set(metadata.grants)];
  metadata.connects = [...new Set(metadata.connects)];
  return metadata;
}

function normalizeScript(source, metadata, existing = null) {
  const id = existing?.id || ('script-' + crypto.randomUUID());
  const token = existing?.token || crypto.randomUUID().replace(/-/g, '');
  return {
    id, token,
    name: metadata.name,
    namespace: metadata.namespace,
    version: metadata.version,
    description: metadata.description,
    source,
    matches: metadata.matches,
    includeGlobs: metadata.includeGlobs,
    excludeMatches: metadata.excludeMatches,
    excludeGlobs: metadata.excludeGlobs,
    grants: metadata.grants,
    connects: metadata.connects,
    runAt: metadata.runAt,
    allFrames: metadata.allFrames,
    world: metadata.world,
    enabled: existing?.enabled !== false,
    createdAt: existing?.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function storageKey(scriptId, key) {
  return 'pasi:userscript:value:' + scriptId + ':' + String(key);
}

function grantName(value) {
  return GRANT_ALIASES.get(value) || value;
}

function hasGrant(script, value) {
  const wanted = grantName(value);
  return script.grants.includes(value) || script.grants.includes(wanted);
}

function wildcardHostnameMatches(hostname, pattern) {
  const value = String(pattern || '').toLowerCase().trim();
  if (!value || value === '*') return true;
  if (value.startsWith('*.')) {
    const suffix = value.slice(1);
    return hostname.endsWith(suffix) && hostname.length > suffix.length;
  }
  return hostname === value;
}

function connectAllowed(script, targetUrl) {
  if (!script.connects.length) return false;
  let url;
  try { url = new URL(targetUrl); } catch (_) { return false; }
  if (!/^https?:$/.test(url.protocol)) return false;
  return script.connects.some((entry) => {
    const rule = String(entry).trim().toLowerCase();
    if (rule === '*') return true;
    if (rule.includes('://')) {
      try {
        const allowed = new URL(rule.includes('/*') ? rule.replace(/\/\*$/, '/') : rule);
        if (allowed.protocol !== url.protocol) return false;
        return wildcardHostnameMatches(url.hostname, allowed.hostname);
      } catch (_) { return false; }
    }
    return wildcardHostnameMatches(url.hostname, rule);
  });
}

function matchOrigins(matches) {
  const origins = new Set();
  for (const pattern of matches) {
    const value = String(pattern || '').trim();
    if (!value) continue;
    if (value === '<all_urls>') {
      origins.add('*://*/*');
      continue;
    }
    const m = value.match(/^(\*|https?|file):\/\/([^/]+)(?:\/.*)?$/i);
    if (!m) continue;
    const scheme = m[1] === '*' ? '*' : m[1].toLowerCase();
    const host = m[2];
    origins.add((scheme + '://' + host + '/*'));
  }
  return [...origins];
}

function createBootstrap(script) {
  const metadata = {
    id: script.id,
    name: script.name,
    namespace: script.namespace,
    version: script.version,
    description: script.description,
    grants: script.grants,
    connects: script.connects,
  };
  const gmSource = JSON.stringify(metadata);
  const grantSet = JSON.stringify(script.grants);
  const id = JSON.stringify(script.id);
  const token = JSON.stringify(script.token);
  const original = script.source.replace(/(?:\/\/|\/*)\s*==UserScript==[\s\S]*?(?:\/\/|\/*)\s*==\/UserScript==/i, '');
  const unsafe = script.world === 'MAIN';
  const lines = [
    '(() => {',
    '  "use strict";',
    '  const SCRIPT_ID = ' + id + ';',
    '  const AUTH = ' + token + ';',
    '  const INFO = Object.freeze({script:' + gmSource + ', scriptHandler:"PASI", version:"1.2.0"});',
    '  const GRANTS = new Set(' + grantSet + ');',
    '  const CONTEXT_ERROR = "PASI userscript extension context invalidated";',
    '  const retryable = /context invalidated|extension context|receiving end|disconnected/i;',
    '  const runtimeAlive = () => { try { return Boolean(globalThis.chrome?.runtime?.id); } catch (_) { return false; } };',
    '  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));',
    '  const safeSendMessage = async (payload, attempt = 0) => {',
    '    if (!runtimeAlive()) {',
    '      if (attempt < 1) { await sleep(50); return safeSendMessage(payload, attempt + 1); }',
    '      throw new Error(CONTEXT_ERROR);',
    '    }',
    '    return new Promise((resolve, reject) => {',
    '      try {',
    '        globalThis.chrome.runtime.sendMessage({source:"pasi-userscript",scriptId:SCRIPT_ID,token:AUTH,...payload}, (response) => {',
    '          const lastError = globalThis.chrome.runtime.lastError;',
    '          if (lastError) {',
    '            const error = new Error(lastError.message || "userscript IPC failed");',
    '            if (attempt < 1 && retryable.test(error.message)) { sleep(50).then(() => safeSendMessage(payload, attempt + 1)).then(resolve, reject); return; }',
    '            reject(error); return;',
    '          }',
    '          resolve(response);',
    '        });',
    '      } catch (error) {',
    '        if (attempt < 1 && retryable.test(String(error?.message || error))) { sleep(50).then(() => safeSendMessage(payload, attempt + 1)).then(resolve, reject); return; }',
    '        reject(error);',
    '      }',
    '    });',
    '  };',
    '  const rpc = (op, data) => safeSendMessage({op, data});',
    '  const assertGrant = (grant) => { if (!GRANTS.has(grant) && !GRANTS.has("GM_fetch") && grant !== "unsafeWindow") throw new Error("PASI userscript grant denied: " + grant); };',
    '  const addStyle = (css) => { const style = document.createElement("style"); style.textContent = String(css); (document.head || document.documentElement).appendChild(style); return style; };',
    '  const clipboard = async (text, type = "text") => { if (type !== "text") throw new Error("PASI clipboard supports text only"); if (!navigator.clipboard?.writeText) throw new Error("clipboard API unavailable"); await navigator.clipboard.writeText(String(text)); };',
    '  const GM = {',
    '    info: INFO,',
    '    getValue: async (key, fallback) => (await rpc("storage.get", {key, fallback})).value,',
    '    setValue: async (key, value) => rpc("storage.set", {key, value}),',
    '    deleteValue: async (key) => rpc("storage.delete", {key}),',
    '    listValues: async () => (await rpc("storage.list")).keys,',
    '    fetch: async (url, options = {}) => { assertGrant("fetch"); return rpc("fetch", {url, options}); },',
    '    webRequest: async (request) => { assertGrant("webRequest"); return rpc("fetch", request); },',
    '    xmlHttpRequest: async (request) => { assertGrant("xmlhttprequest"); return rpc("fetch", request); },',
    '    registerMenuCommand: async (caption, command, accessKey) => { assertGrant("menu"); return rpc("menu.register", {caption, command, accessKey}); },',
    '    unregisterMenuCommand: async (menuId) => { assertGrant("menu"); return rpc("menu.unregister", {menuId}); },',
    '    notification: async (details) => { assertGrant("notifications"); return rpc("notifications.create", details); },',
    '    download: async (details) => { assertGrant("downloads"); return rpc("downloads.create", details); },',
    '    openInTab: async (url, options = {}) => { assertGrant("tabs"); return rpc("tabs.open", {url, options}); },',
    '    setClipboard: clipboard,',
    '    addStyle,',
    '  };',
    unsafe ? '  GM.unsafeWindow = globalThis;' : '',
    '  globalThis.GM = Object.freeze(GM);',
    '  globalThis.GM_info = INFO;',
    '  globalThis.GM_getValue = GM.getValue;',
    '  globalThis.GM_setValue = GM.setValue;',
    '  globalThis.GM_deleteValue = GM.deleteValue;',
    '  globalThis.GM_listValues = GM.listValues;',
    '  globalThis.GM_fetch = GM.fetch;',
    '  globalThis.GM_webRequest = GM.webRequest;',
    '  globalThis.GM_xmlhttpRequest = GM.xmlHttpRequest;',
    '  globalThis.GM_registerMenuCommand = GM.registerMenuCommand;',
    '  globalThis.GM_unregisterMenuCommand = GM.unregisterMenuCommand;',
    '  globalThis.GM_notification = GM.notification;',
    '  globalThis.GM_download = GM.download;',
    '  globalThis.GM_openInTab = GM.openInTab;',
    '  globalThis.GM_setClipboard = GM.setClipboard;',
    '  globalThis.GM_addStyle = GM.addStyle;',
    original,
    '})();',
    '// PASI_GENERATED_USER_SCRIPT_END',
  ];
  return lines.filter((line) => line !== '').join('\n');
}

async function readStore() {
  try {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    return Array.isArray(result?.[STORAGE_KEY]) ? result[STORAGE_KEY] : [];
  } catch (_) {
    return [];
  }
}

async function writeStore(scripts) {
  await chrome.storage.local.set({[STORAGE_KEY]: scripts});
}

async function scriptById(id) {
  return (await readStore()).find((script) => script.id === id) || null;
}

async function userScriptsCall(method, ...args) {
  return withContextRecovery(async () => {
    if (!apiAvailable()) {
      throw new Error('PASI userscript API is unavailable; enable Allow User Scripts in the extension details');
    }
    return chrome.userScripts[method](...args);
  });
}

async function hostPermissionsGranted(script) {
  const origins = matchOrigins(script.matches);
  if (!origins.length || !chrome.permissions?.contains) return true;
  return chrome.permissions.contains({origins});
}

async function configureWorld(script) {
  if (typeof chrome.userScripts?.configureWorld !== 'function') return;
  await userScriptsCall('configureWorld', {
    worldId: 'pasi-us-' + script.id,
    messaging: script.world === 'USER_SCRIPT',
  });
}

async function registerOne(script) {
  if (!script.enabled) return {id: script.id, status: 'disabled'};
  if (!(await hostPermissionsGranted(script))) {
    return {id: script.id, status: 'permission_required', origins: matchOrigins(script.matches)};
  }
  await configureWorld(script);
  await userScriptsCall('unregister', {ids: [script.id]}).catch(() => {});
  const registration = {
    id: script.id,
    matches: script.matches,
    includeGlobs: script.includeGlobs,
    excludeMatches: script.excludeMatches,
    excludeGlobs: script.excludeGlobs,
    runAt: script.runAt,
    allFrames: script.allFrames,
    js: [{code: createBootstrap(script)}],
  };
  if (script.world === 'MAIN') registration.world = 'MAIN';
  else {
    registration.world = 'USER_SCRIPT';
    registration.worldId = 'pasi-us-' + script.id;
  }
  await userScriptsCall('register', [registration]);
  return {id: script.id, status: 'registered'};
}

async function syncMainWorldBridge(scripts) {
  if (!chrome.scripting?.registerContentScripts) return;
  await chrome.scripting.unregisterContentScripts({ids: [MAIN_BRIDGE_ID]}).catch(() => {});
  const main = scripts.filter((script) => script.enabled && script.world === 'MAIN');
  if (!main.length) return;
  const matches = [...new Set(main.flatMap((script) => script.matches))];
  const origins = matchOrigins(matches);
  if (chrome.permissions?.contains && !(await chrome.permissions.contains({origins}))) return;
  await chrome.scripting.registerContentScripts([{
    id: MAIN_BRIDGE_ID,
    matches,
    js: ['userscript-bridge.js'],
    runAt: 'document_start',
    allFrames: false,
    persistAcrossSessions: true,
  }]);
}

async function syncAll() {
  return serializeMutation(async () => {
    const scripts = await readStore();
    const results = [];
    for (const script of scripts) {
      try { results.push(await registerOne(script)); }
      catch (error) { results.push({id: script.id, status: 'error', error: String(error?.message || error)}); }
    }
    await syncMainWorldBridge(scripts);
    return results;
  });
}

function requireGrant(script, operation) {
  const grant = grantName(operation);
  if (!hasGrant(script, operation) && !hasGrant(script, grant)) {
    throw new Error('PASI userscript grant denied: ' + operation);
  }
}

async function requireAuthorized(message) {
  const script = await scriptById(message?.scriptId);
  if (!script || !script.enabled || script.token !== message.token) {
    throw new Error('PASI userscript authentication failed');
  }
  return script;
}

async function rpc(script, op, data, sender) {
  switch (op) {
    case 'storage.get': {
      requireGrant(script, 'storage');
      const key = storageKey(script.id, data?.key);
      const result = await chrome.storage.local.get(key);
      return {value: result?.[key] ?? data?.fallback};
    }
    case 'storage.set': {
      requireGrant(script, 'storage');
      const encoded = JSON.stringify(data?.value);
      if (encoded.length > MAX_RPC_BODY_CHARS) throw new Error('userscript value is too large');
      await chrome.storage.local.set({[storageKey(script.id, data?.key)]: data?.value});
      return {ok: true};
    }
    case 'storage.delete':
      requireGrant(script, 'storage');
      await chrome.storage.local.remove(storageKey(script.id, data?.key));
      return {ok: true};
    case 'storage.list': {
      requireGrant(script, 'storage');
      const all = await chrome.storage.local.get(null);
      const prefix = 'pasi:userscript:value:' + script.id + ':';
      return {keys: Object.keys(all).filter((key) => key.startsWith(prefix)).map((key) => key.slice(prefix.length)).slice(0, MAX_VALUES)};
    }
    case 'fetch': {
      requireGrant(script, 'fetch');
      const url = String(data?.url || '');
      if (!connectAllowed(script, url)) throw new Error('@connect denied for ' + url);
      const options = data?.options || data || {};
      const response = await fetch(url, {
        method: options.method || 'GET',
        headers: options.headers || {},
        body: options.body == null ? undefined : String(options.body),
        redirect: options.redirect || 'follow',
      });
      const text = await response.text();
      if (text.length > MAX_RPC_BODY_CHARS) throw new Error('userscript response exceeded size limit');
      return {
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        url: response.url,
        headers: Object.fromEntries(response.headers.entries()),
        responseText: text,
        response: text,
      };
    }
    case 'menu.register': {
      requireGrant(script, 'menu');
      const menuId = 'pasi-us-menu-' + script.id + '-' + crypto.randomUUID();
      const menu = {id:menuId, scriptId:script.id, tabId:sender?.tab?.id ?? null, caption:String(data?.caption || '').slice(0,200), accessKey:data?.accessKey || null, command:String(data?.command || '')};
      const stored = await chrome.storage.session.get('pasi:userscript:menus');
      const menus = Array.isArray(stored?.['pasi:userscript:menus']) ? stored['pasi:userscript:menus'] : [];
      menus.push(menu);
      await chrome.storage.session.set({'pasi:userscript:menus': menus.slice(-500)});
      if (chrome.contextMenus?.create) await chrome.contextMenus.create({id:menuId,title:menu.caption,contexts:['page']});
      return {menuId};
    }
    case 'menu.unregister': {
      requireGrant(script, 'menu');
      if (chrome.contextMenus?.remove) await chrome.contextMenus.remove(data?.menuId).catch(() => {});
      const stored = await chrome.storage.session.get('pasi:userscript:menus');
      const menus = Array.isArray(stored?.['pasi:userscript:menus']) ? stored['pasi:userscript:menus'] : [];
      await chrome.storage.session.set({'pasi:userscript:menus': menus.filter((item) => item.id !== data?.menuId || item.scriptId !== script.id)});
      return {ok:true};
    }
    case 'notifications.create':
      requireGrant(script, 'notifications');
      return {notificationId: await chrome.notifications.create('pasi-us-' + script.id + '-' + Date.now(), {type:'basic', iconUrl:chrome.runtime.getURL('icons/icon128.png'), title:String(data?.title || script.name), message:String(data?.text || data?.message || '').slice(0,500)})};
    case 'downloads.create':
      requireGrant(script, 'downloads');
      return {downloadId: await chrome.downloads.download({url:String(data?.url || ''), filename:data?.name ? String(data.name) : undefined, saveAs:data?.saveAs === true})};
    case 'tabs.open':
      requireGrant(script, 'tabs');
      return {tabId:(await chrome.tabs.create({url:String(data?.url || ''), active:data?.options?.active !== false})).id};
    default:
      throw new Error('Unknown userscript RPC operation: ' + op);
  }
}

async function handleMessage(message, sender, sendResponse) {
  try {
    const script = await requireAuthorized(message);
    const result = await rpc(script, message.op, message.data || {}, sender);
    sendResponse({ok:true, result});
  } catch (error) {
    sendResponse({ok:false, error:String(error?.message || error)});
  }
  return true;
}

async function installScript(source, existing = null) {
  return serializeMutation(async () => {
    const metadata = parseMetadata(source);
    const script = normalizeScript(source, metadata, existing);
    const store = await readStore();
    const next = store.filter((item) => item.id !== script.id);
    next.push(script);
    await writeStore(next);
    const result = await registerOne(script);
    await syncMainWorldBridge(next);
    return {script, result, requiredOrigins:matchOrigins(script.matches)};
  });
}

async function removeScript(id) {
  return serializeMutation(async () => {
    const store = await readStore();
    const existing = store.find((script) => script.id === id);
    if (!existing) return false;
    await userScriptsCall('unregister', {ids:[id]}).catch(() => {});
    const next = store.filter((script) => script.id !== id);
    await writeStore(next);
    await syncMainWorldBridge(next);
    const all = await chrome.storage.local.get(null);
    const keys = Object.keys(all).filter((key) => key.startsWith('pasi:userscript:value:' + id + ':'));
    if (keys.length) await chrome.storage.local.remove(keys);
    return true;
  });
}

async function setEnabled(id, enabled) {
  return serializeMutation(async () => {
    const store = await readStore();
    const next = store.map((script) => script.id === id ? {...script, enabled:Boolean(enabled), updatedAt:new Date().toISOString()} : script);
    const updated = next.find((script) => script.id === id);
    if (!updated) throw new Error('unknown userscript ' + id);
    await writeStore(next);
    if (updated.enabled) await registerOne(updated);
    else await userScriptsCall('unregister', {ids:[id]}).catch(() => {});
    await syncMainWorldBridge(next);
    return updated;
  });
}

async function getMenus() {
  const result = await chrome.storage.session.get('pasi:userscript:menus');
  return Array.isArray(result?.['pasi:userscript:menus']) ? result['pasi:userscript:menus'] : [];
}

async function getPublicState() {
  const scripts = await readStore();
  let registered = [];
  let apiError = null;
  try { registered = await userScriptsCall('getScripts'); } catch (error) { apiError = String(error?.message || error); }
  return {
    apiAvailable:apiAvailable(),
    apiError,
    scripts:scripts.map(({token, source, ...publicScript}) => publicScript),
    registered:registered.map(({id, matches, runAt, world, worldId}) => ({id, matches, runAt, world, worldId})),
    menus:await getMenus(),
  };
}

async function getBridgeConfig() {
  const scripts = await readStore();
  return scripts.filter((script) => script.enabled && script.world === 'MAIN').map((script) => ({id:script.id, token:script.token}));
}

if (globalThis.chrome?.runtime?.onInstalled) {
  chrome.runtime.onInstalled.addListener((details) => {
    if (details.reason === 'update' || details.reason === 'install') {
      void syncAll().catch((error) => console.warn('[PASI userscripts] sync failed', error));
    }
  });
}
if (globalThis.chrome?.runtime?.onStartup) {
  chrome.runtime.onStartup.addListener(() => {
    void syncAll().catch((error) => console.warn('[PASI userscripts] startup sync failed', error));
  });
}
if (globalThis.chrome?.runtime?.onUserScriptMessage) {
  chrome.runtime.onUserScriptMessage.addListener((message, sender, sendResponse) => { void handleMessage(message, sender, sendResponse); return true; });
} else if (globalThis.chrome?.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.source !== 'pasi-userscript' && message?.source !== 'pasi-userscript-bridge') return false;
    void handleMessage(message, sender, sendResponse);
    return true;
  });
}
if (globalThis.chrome?.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.source === 'pasi-userscript-bridge-init') {
      void getBridgeConfig().then((result) => sendResponse({ok:true,result})).catch((error) => sendResponse({ok:false,error:String(error?.message || error)}));
      return true;
    }
    if (message?.source !== 'pasi-userscript-management') return false;
    (async () => {
      try {
        if (message.op === 'install') return sendResponse({ok:true,result:await installScript(message.sourceText)});
        if (message.op === 'update') {
          const existing = await scriptById(message.id);
          if (!existing) throw new Error('unknown userscript');
          return sendResponse({ok:true,result:await installScript(message.sourceText, existing)});
        }
        if (message.op === 'remove') return sendResponse({ok:true,result:await removeScript(message.id)});
        if (message.op === 'enable') return sendResponse({ok:true,result:await setEnabled(message.id, true)});
        if (message.op === 'disable') return sendResponse({ok:true,result:await setEnabled(message.id, false)});
        if (message.op === 'state') return sendResponse({ok:true,result:await getPublicState()});
        throw new Error('unknown userscript management operation');
      } catch (error) { sendResponse({ok:false,error:String(error?.message || error)}); }
    })();
    return true;
  });
}

globalThis.PASI_USERSCRIPT_RUNTIME = Object.freeze({
  parseMetadata,
  normalizeScript,
  createBootstrap,
  connectAllowed,
  matchOrigins,
  getBridgeConfig,
  installScript,
  removeScript,
  setEnabled,
  syncAll,
  getPublicState,
});
globalThis.PASI_USERSCRIPT_RUNTIME_UTILS = Object.freeze({
  parseMetadata,
  createBootstrap,
  connectAllowed,
  matchOrigins,
  grantName,
});
