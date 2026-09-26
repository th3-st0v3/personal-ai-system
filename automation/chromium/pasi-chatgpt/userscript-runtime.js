/* global chrome */
'use strict';

const USERSCRIPT_STORE = 'pasi:userscripts:v1';
const MENU_STORE = 'pasi:userscript:menus';
const MAIN_BRIDGE_ID = 'pasi-userscript-main-bridge';
const MAX_SOURCE_CHARS = 2 * 1024 * 1024;
const MAX_RPC_TEXT_CHARS = 5 * 1024 * 1024;
const MAX_MENU_ITEMS = 500;
const MAX_NETWORK_RULES = 50;
const MAX_NETWORK_RULE_BYTES = 20 * 1024;
const DNR_STORE_PREFIX = 'pasi:userscript:dnr:';
const GRANT_ALIASES = Object.freeze({
  'GM_getValue': 'storage',
  'GM_setValue': 'storage',
  'GM_deleteValue': 'storage',
  'GM_listValues': 'storage',
  'GM_xmlhttpRequest': 'xmlhttprequest',
  'GM_webRequest': 'webRequest',
  'GM_fetch': 'fetch',
  'GM_registerMenuCommand': 'menu',
  'GM_unregisterMenuCommand': 'menu',
  'GM_notification': 'notifications',
  'GM_download': 'downloads',
  'GM_openInTab': 'tabs',
  'GM_setClipboard': 'clipboard',
  'unsafeWindow': 'unsafeWindow'
});

let mutationTail = Promise.resolve();

function serializeMutation(task) {
  const next = mutationTail.then(task, task);
  mutationTail = next.catch(() => undefined);
  return next;
}

function extensionContextAlive() {
  try {
    return Boolean(chrome.runtime && chrome.runtime.id);
  } catch (_) {
    return false;
  }
}

function hasUserScriptsApi() {
  return Boolean(
    globalThis.chrome &&
    chrome.userScripts &&
    typeof chrome.userScripts.getScripts === 'function'
  );
}

async function userScriptsCall(method, ...args) {
  if (!extensionContextAlive()) {
    throw new Error('Extension context invalidated');
  }
  if (!hasUserScriptsApi()) {
    throw new Error('PASI userScripts API is unavailable; enable Allow User Scripts in the extension details');
  }
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await chrome.userScripts[method](...args);
    } catch (error) {
      lastError = error;
      const message = String(error && error.message ? error.message : error);
      if (!/context invalidated|extension context|receiving end|disconnected/i.test(message) || attempt) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  throw lastError;
}

function parseMetadata(source) {
  if (typeof source !== 'string' || source.length > MAX_SOURCE_CHARS) {
    throw new Error('userscript source is missing or exceeds the 2 MiB limit');
  }
  const block = source.match(
    /(?:\/\/|\/\*)\s*==UserScript==([\s\S]*?)(?:\/\/|\/\*)\s*==\/UserScript==/i
  );
  if (!block) throw new Error('userscript metadata block not found');

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
    world: 'USER_SCRIPT'
  };

  for (const line of block[1].split(/\r?\n/)) {
    const clean = line.replace(/^\s*\*?\s*|\s*$/g, '');
    const match = clean.match(/^@([A-Za-z][\w-]*)(?:\s+(.+))?$/);
    if (!match) continue;
    const key = match[1].toLowerCase();
    const value = String(match[2] || '').trim();
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

  if (!metadata.matches.length) {
    throw new Error('userscript must declare at least one @match');
  }
  if (metadata.world === 'MAIN' && !metadata.grants.includes('unsafeWindow')) {
    metadata.grants.push('unsafeWindow');
  }
  metadata.grants = [...new Set(metadata.grants)];
  metadata.connects = [...new Set(metadata.connects)];
  return metadata;
}

function normalizeScript(source, metadata, existing, allowUnsafeWorld) {
  const unsafeConfirmed = metadata.world !== 'MAIN' ||
    Boolean(existing && existing.unsafeConfirmed) ||
    allowUnsafeWorld === true;

  return {
    id: existing && existing.id ? existing.id : 'script-' + crypto.randomUUID(),
    token: existing && existing.token ? existing.token : crypto.randomUUID().replace(/-/g, ''),
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
    unsafeConfirmed,
    enabled: existing ? existing.enabled !== false : true,
    createdAt: existing && existing.createdAt ? existing.createdAt : new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };
}

function grantAllowed(grants, requested) {
  if (grants.includes(requested)) return true;
  if (requested === 'storage') {
    return ['GM_getValue', 'GM_setValue', 'GM_deleteValue', 'GM_listValues'].some((grant) => grants.includes(grant));
  }
  const aliases = Object.keys(GRANT_ALIASES);
  return aliases.some((grant) => GRANT_ALIASES[grant] === requested && grants.includes(grant));
}

function requireGrant(script, requested) {
  if (!grantAllowed(script.grants, requested)) {
    throw new Error('PASI userscript grant denied: ' + requested);
  }
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
  try {
    url = new URL(targetUrl);
  } catch (_) {
    return false;
  }
  if (!/^https?:$/.test(url.protocol)) return false;

  return script.connects.some((entry) => {
    const rule = String(entry).trim().toLowerCase();
    if (rule === '*') return true;
    if (rule.includes('://')) {
      try {
        const parsed = new URL(rule.replace(/\/\*$/, '/'));
        return parsed.protocol === url.protocol &&
          wildcardHostnameMatches(url.hostname, parsed.hostname);
      } catch (_) {
        return false;
      }
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
    const parsed = value.match(/^(\*|https?|file):\/\/([^/]+)(?:\/.*)?$/i);
    if (!parsed) continue;
    const scheme = parsed[1] === '*' ? '*' : parsed[1].toLowerCase();
    origins.add(scheme + '://' + parsed[2] + '/*');
  }
  return [...origins];
}

function stripMetadata(source) {
  return source.replace(
    /(?:\/\/|\/\*)\s*==UserScript==[\s\S]*?(?:\/\/|\/\*)\s*==\/UserScript==/i,
    ''
  );
}

function createBootstrap(script) {
  const info = JSON.stringify({
    id: script.id,
    name: script.name,
    namespace: script.namespace,
    version: script.version,
    description: script.description,
    grants: script.grants,
    connects: script.connects
  });
  const grants = JSON.stringify(script.grants);
  const id = JSON.stringify(script.id);
  const token = JSON.stringify(script.token);
  const body = stripMetadata(script.source);
  const mainWorld = script.world === 'MAIN';
  const lines = [
    '(() => {',
    '  "use strict";',
    '  const SCRIPT_ID = ' + id + ';',
    '  const AUTH = ' + token + ';',
    '  const INFO = Object.freeze({script:' + info + ', scriptHandler:"PASI", version:"1.2.0"});',
    '  const GRANTS = new Set(' + grants + ');',
    '  const grantAllowed = (name) => GRANTS.has(name) || ({storage:["GM_getValue","GM_setValue","GM_deleteValue","GM_listValues"],fetch:["GM_fetch"],xmlhttprequest:["GM_xmlhttpRequest"],webRequest:["GM_webRequest"],menu:["GM_registerMenuCommand","GM_unregisterMenuCommand"],notifications:["GM_notification"],downloads:["GM_download"],tabs:["GM_openInTab"],clipboard:["GM_setClipboard"]}[name] || []).some((alias) => GRANTS.has(alias));',
    '  const assertGrant = (name) => { if (!grantAllowed(name) && name !== "unsafeWindow") throw new Error("PASI userscript grant denied: " + name); };',
    '  const addStyle = (css) => { const style = document.createElement("style"); style.textContent = String(css); (document.head || document.documentElement).appendChild(style); return style; };',
    '  const setClipboard = async (text, type) => { assertGrant("clipboard"); if (type && type !== "text") throw new Error("PASI clipboard supports text only"); if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("clipboard API unavailable"); await navigator.clipboard.writeText(String(text)); };'
  ];

  if (mainWorld) {
    lines.push(
      '  const bridgeRpc = (op, data) => new Promise((resolve, reject) => {',
      '    const requestId = "pasi-us-" + Math.random().toString(36).slice(2);',
      '    let timeoutId;',
      '    const listener = (event) => { const value = event.data; if (!value || value.source !== "pasi-userscript-main-response" || value.requestId !== requestId) return; clearTimeout(timeoutId); window.removeEventListener("message", listener); if (value.ok) resolve(value.result); else reject(new Error(value.error || "userscript bridge request failed")); };',
      '    window.addEventListener("message", listener);',
      '    window.postMessage({source:"pasi-userscript-main", requestId, scriptId:SCRIPT_ID, token:AUTH, op, data}, "*");',
      '    timeoutId = setTimeout(() => { window.removeEventListener("message", listener); reject(new Error("PASI userscript bridge timeout")); }, 10000);',
      '  });',
      '  const rpc = bridgeRpc;'
    );
  } else {
    lines.push(
      '  const runtimeAlive = () => { try { return Boolean(globalThis.chrome && chrome.runtime && chrome.runtime.id); } catch (_) { return false; } };',
      '  const safeSendMessage = async (payload, attempt = 0) => {',
      '    if (!runtimeAlive()) { if (attempt < 1) { await new Promise((resolve) => setTimeout(resolve, 50)); return safeSendMessage(payload, attempt + 1); } throw new Error("PASI userscript extension context invalidated"); }',
      '    return new Promise((resolve, reject) => {',
      '      try {',
      '        chrome.runtime.sendMessage({source:"pasi-userscript", scriptId:SCRIPT_ID, token:AUTH, ...payload}, (response) => {',
      '          const error = chrome.runtime.lastError;',
      '          if (error) { if (attempt < 1 && /context invalidated|extension context|receiving end|disconnected/i.test(error.message || "")) { setTimeout(() => safeSendMessage(payload, attempt + 1).then(resolve, reject), 50); return; } reject(new Error(error.message || "userscript IPC failed")); return; }',
      '          resolve(response);',
      '        });',
      '      } catch (error) { if (attempt < 1 && /context invalidated|extension context|receiving end|disconnected/i.test(String(error && error.message || error))) { setTimeout(() => safeSendMessage(payload, attempt + 1).then(resolve, reject), 50); return; } reject(error); }',
      '    });',
      '  };',
      '  const rpc = (op, data) => safeSendMessage({op, data});'
    );
  }

  lines.push(
    '  const menuCallbacks = Object.create(null);',
    '  const GM = {',
    '    info: INFO,',
    '    getValue: async (key, fallback) => (await rpc("storage.get", {key, fallback})).value,',
    '    setValue: async (key, value) => rpc("storage.set", {key, value}),',
    '    deleteValue: async (key) => rpc("storage.delete", {key}),',
    '    listValues: async () => (await rpc("storage.list")).keys,',
    '    fetch: async (url, options) => { assertGrant("fetch"); return rpc("fetch", {url, options:options || {}}); },',
    '    webRequest: async (request) => { assertGrant("webRequest"); return rpc(request && (request.addRules || request.removeRuleIds) ? "webRequest.rules" : "fetch", request || {}); },',
    '    xmlHttpRequest: async (request) => { assertGrant("xmlhttprequest"); return rpc("fetch", request || {}); },',
    '    registerMenuCommand: async (caption, command, accessKey) => { assertGrant("menu"); const result = await rpc("menu.register", {caption, accessKey}); if (result && result.menuId && typeof command === "function") menuCallbacks[result.menuId] = command; return result ? result.menuId : undefined; },',
    '    unregisterMenuCommand: async (menuId) => { assertGrant("menu"); delete menuCallbacks[menuId]; return rpc("menu.unregister", {menuId}); },',
    '    notification: async (details) => { assertGrant("notifications"); return rpc("notifications.create", details || {}); },',
    '    download: async (details) => { assertGrant("downloads"); return rpc("downloads.create", details || {}); },',
    '    openInTab: async (url, options) => { assertGrant("tabs"); return rpc("tabs.open", {url, options:options || {}}); },',
    '    setClipboard,',
    '    addStyle',
    '  };',
    mainWorld ? '  GM.unsafeWindow = globalThis;' : '',
    '  globalThis.__PASI_GM_MENU_CALLBACKS = menuCallbacks;',
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
    body,
    '})();',
    '// PASI_GENERATED_USER_SCRIPT_END'
  );

  return lines.filter(Boolean).join('\n');
}

async function readScripts() {
  const stored = await chrome.storage.local.get(USERSCRIPT_STORE);
  return Array.isArray(stored && stored[USERSCRIPT_STORE]) ? stored[USERSCRIPT_STORE] : [];
}

async function writeScripts(scripts) {
  await chrome.storage.local.set({[USERSCRIPT_STORE]: scripts});
}

async function scriptById(id) {
  return (await readScripts()).find((script) => script.id === id) || null;
}

async function hostPermissionsGranted(script) {
  const origins = matchOrigins(script.matches);
  if (!origins.length || !chrome.permissions || !chrome.permissions.contains) return true;
  return chrome.permissions.contains({origins});
}

async function configureWorld(script) {
  if (!chrome.userScripts || typeof chrome.userScripts.configureWorld !== 'function') return;
  await userScriptsCall('configureWorld', {
    worldId: 'pasi-us-' + script.id,
    messaging: script.world === 'USER_SCRIPT'
  });
}

async function registerOne(script) {
  if (!script.enabled) return {id:script.id, status:'disabled'};
  if (script.world === 'MAIN' && !script.unsafeConfirmed) {
    return {id:script.id, status:'unsafe_confirmation_required'};
  }
  if (!(await hostPermissionsGranted(script))) {
    return {id:script.id, status:'permission_required', origins:matchOrigins(script.matches)};
  }

  await configureWorld(script);
  await userScriptsCall('unregister', {ids:[script.id]}).catch(() => {});

  const registration = {
    id:script.id,
    matches:script.matches,
    includeGlobs:script.includeGlobs,
    excludeMatches:script.excludeMatches,
    excludeGlobs:script.excludeGlobs,
    runAt:script.runAt,
    allFrames:script.allFrames,
    world:script.world,
    js:[{code:createBootstrap(script)}]
  };

  if (script.world === 'USER_SCRIPT') {
    registration.worldId = 'pasi-us-' + script.id;
  }

  await userScriptsCall('register', [registration]);
  return {id:script.id, status:'registered'};
}

async function syncMainWorldBridge(scripts) {
  if (!chrome.scripting || !chrome.scripting.registerContentScripts) return;
  await chrome.scripting.unregisterContentScripts({ids:[MAIN_BRIDGE_ID]}).catch(() => {});

  const mainScripts = scripts.filter((script) => script.enabled && script.world === 'MAIN');
  if (!mainScripts.length) return;

  const matches = [...new Set(mainScripts.flatMap((script) => script.matches))];
  const origins = matchOrigins(matches);
  if (chrome.permissions && chrome.permissions.contains && !(await chrome.permissions.contains({origins}))) return;

  await chrome.scripting.registerContentScripts([{
    id:MAIN_BRIDGE_ID,
    matches,
    js:['userscript-bridge.js'],
    runAt:'document_start',
    persistAcrossSessions:true
  }]);
}

async function syncAll() {
  return serializeMutation(async () => {
    const scripts = await readScripts();
    const results = [];
    for (const script of scripts) {
      try {
        results.push(await registerOne(script));
      } catch (error) {
        results.push({
          id:script.id,
          status:'error',
          error:String(error && error.message ? error.message : error)
        });
      }
    }
    await syncMainWorldBridge(scripts);
    return results;
  });
}

function storageKey(scriptId, key) {
  return 'pasi:userscript:value:' + scriptId + ':' + String(key);
}

async function rpc(script, op, data, sender) {
  switch (op) {
    case 'storage.get': {
      requireGrant(script, 'storage');
      const key = storageKey(script.id, data && data.key);
      const stored = await chrome.storage.local.get(key);
      return {value:stored && Object.prototype.hasOwnProperty.call(stored, key) ? stored[key] : data && data.fallback};
    }
    case 'storage.set': {
      requireGrant(script, 'storage');
      const encoded = JSON.stringify(data && data.value);
      if (encoded && encoded.length > MAX_RPC_TEXT_CHARS) throw new Error('userscript value is too large');
      await chrome.storage.local.set({[storageKey(script.id, data && data.key)]:data && data.value});
      return {ok:true};
    }
    case 'storage.delete':
      requireGrant(script, 'storage');
      await chrome.storage.local.remove(storageKey(script.id, data && data.key));
      return {ok:true};
    case 'storage.list': {
      requireGrant(script, 'storage');
      const all = await chrome.storage.local.get(null);
      const prefix = 'pasi:userscript:value:' + script.id + ':';
      return {
        keys:Object.keys(all).filter((key) => key.startsWith(prefix)).map((key) => key.slice(prefix.length))
      };
    }
    case 'webRequest.rules':
      return applyNetworkRules(script, data || {});
    case 'fetch': {
      requireGrant(script, 'fetch');
      const url = String(data && data.url || '');
      if (!connectAllowed(script, url)) throw new Error('@connect denied for ' + url);
      const options = (data && data.options) || {};
      const response = await fetch(url, {
        method:options.method || 'GET',
        headers:options.headers || {},
        body:options.body == null ? undefined : String(options.body),
        redirect:options.redirect || 'follow'
      });
      const text = await response.text();
      if (text.length > MAX_RPC_TEXT_CHARS) throw new Error('userscript response exceeded size limit');
      return {
        ok:response.ok,
        status:response.status,
        statusText:response.statusText,
        url:response.url,
        headers:Object.fromEntries(response.headers.entries()),
        responseText:text
      };
    }
    case 'menu.register': {
      requireGrant(script, 'menu');
      if (!chrome.contextMenus || !chrome.contextMenus.create) {
        throw new Error('contextMenus permission is required for GM_registerMenuCommand');
      }
      const menuId = 'pasi-us-menu-' + script.id + '-' + crypto.randomUUID();
      await chrome.contextMenus.create({
        id:menuId,
        title:String(data && data.caption || '').slice(0, 200),
        contexts:['page']
      });
      const stored = await chrome.storage.session.get(MENU_STORE);
      const menus = Array.isArray(stored && stored[MENU_STORE]) ? stored[MENU_STORE] : [];
      menus.push({
        id:menuId,
        scriptId:script.id,
        caption:String(data && data.caption || '').slice(0, 200),
        accessKey:data && data.accessKey || null,
        tabId:sender && sender.tab ? sender.tab.id : null
      });
      await chrome.storage.session.set({[MENU_STORE]:menus.slice(-MAX_MENU_ITEMS)});
      return {menuId};
    }
    case 'menu.unregister': {
      requireGrant(script, 'menu');
      if (chrome.contextMenus && chrome.contextMenus.remove) {
        await chrome.contextMenus.remove(data && data.menuId).catch(() => {});
      }
      const stored = await chrome.storage.session.get(MENU_STORE);
      const menus = Array.isArray(stored && stored[MENU_STORE]) ? stored[MENU_STORE] : [];
      await chrome.storage.session.set({
        [MENU_STORE]:menus.filter((item) => item.id !== (data && data.menuId) || item.scriptId !== script.id)
      });
      return {ok:true};
    }
    case 'notifications.create':
      requireGrant(script, 'notifications');
      return {
        notificationId:await chrome.notifications.create(
          'pasi-us-' + script.id + '-' + Date.now(),
          {
            type:'basic',
            iconUrl:'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" rx="24" fill="#111827"/><text x="64" y="78" text-anchor="middle" font-family="Arial" font-size="72" fill="#ffffff">P</text></svg>'),
            title:String(data && data.title || script.name),
            message:String(data && (data.text || data.message) || '').slice(0, 500)
          }
        )
      };
    case 'downloads.create':
      requireGrant(script, 'downloads');
      return {
        downloadId:await chrome.downloads.download({
          url:String(data && data.url || ''),
          filename:data && data.name ? String(data.name) : undefined,
          saveAs:Boolean(data && data.saveAs)
        })
      };
    case 'tabs.open':
      requireGrant(script, 'tabs');
      return {
        tabId:(await chrome.tabs.create({
          url:String(data && data.url || ''),
          active:!data || !data.options || data.options.active !== false
        })).id
      };
    default:
      throw new Error('unknown userscript RPC operation: ' + op);
  }
}

async function authorizedScript(message) {
  const script = await scriptById(message && message.scriptId);
  if (!script || !script.enabled || script.token !== message.token) {
    throw new Error('PASI userscript authentication failed');
  }
  return script;
}

function sendRpcResponse(sendResponse, promise) {
  promise
    .then((result) => sendResponse({ok:true, result}))
    .catch((error) => sendResponse({ok:false, error:String(error && error.message ? error.message : error)}));
  return true;
}

async function clearNetworkRules(scriptId) {
  if (!chrome.declarativeNetRequest || typeof chrome.declarativeNetRequest.updateDynamicRules !== 'function') return;
  const key = DNR_STORE_PREFIX + scriptId;
  const stored = await chrome.storage.local.get(key);
  const ids = Array.isArray(stored && stored[key]) ? stored[key].map(Number).filter(Number.isInteger) : [];
  if (ids.length) {
    await chrome.declarativeNetRequest.updateDynamicRules({removeRuleIds:ids});
  }
  await chrome.storage.local.remove(key);
}

function localDnrId(scriptId, localId, salt) {
  let hash = 2166136261;
  const text = scriptId + ':' + String(localId) + ':' + String(salt);
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % 2000000000 + 1;
}

async function applyNetworkRules(script, data) {
  requireGrant(script, 'webRequest');
  if (!chrome.declarativeNetRequest || typeof chrome.declarativeNetRequest.updateDynamicRules !== 'function') {
    throw new Error('declarativeNetRequestWithHostAccess permission is required for GM_webRequest rules');
  }
  const addRules = Array.isArray(data && data.addRules) ? data.addRules : [];
  const removeLocalIds = Array.isArray(data && data.removeRuleIds) ? data.removeRuleIds.map(Number).filter(Number.isInteger) : [];
  if (addRules.length > MAX_NETWORK_RULES) throw new Error('userscript DNR update exceeds the per-request rule limit');

  const key = DNR_STORE_PREFIX + script.id;
  const stored = await chrome.storage.local.get(key);
  const existingMap = Array.isArray(stored && stored[key]) ? stored[key] : [];
  const removeDnrIds = existingMap.filter((item) => removeLocalIds.includes(Number(item.localId))).map((item) => Number(item.dnrId));
  const keepMap = existingMap.filter((item) => !removeLocalIds.includes(Number(item.localId)));

  const dynamic = typeof chrome.declarativeNetRequest.getDynamicRules === 'function'
    ? await chrome.declarativeNetRequest.getDynamicRules()
    : [];
  const occupied = new Set(dynamic.map((rule) => Number(rule.id)));

  const normalized = [];
  const newMap = keepMap.slice();
  for (const input of addRules) {
    const localId = Number(input && input.id);
    if (!Number.isInteger(localId) || localId < 1) throw new Error('GM_webRequest rule id must be a positive integer');
    const rule = {...input};
    delete rule.id;
    const bytes = JSON.stringify(rule).length;
    if (bytes > MAX_NETWORK_RULE_BYTES) throw new Error('GM_webRequest rule exceeds 20 KiB');
    if (!rule.condition || !rule.action || typeof rule.action.type !== 'string') {
      throw new Error('GM_webRequest rule requires condition and action');
    }
    let dnrId = 0;
    for (let salt = 0; salt < 100; salt += 1) {
      const candidate = localDnrId(script.id, localId, salt);
      if (!occupied.has(candidate) && !newMap.some((item) => Number(item.dnrId) === candidate)) {
        dnrId = candidate;
        break;
      }
    }
    if (!dnrId) throw new Error('unable to allocate a unique DNR rule id');
    normalized.push({...rule, id:dnrId});
    newMap.push({localId, dnrId});
  }

  const allRuleIds = [...new Set([...removeDnrIds, ...normalized.map((rule) => rule.id)])];
  if (allRuleIds.length > MAX_NETWORK_RULES * 2) throw new Error('userscript DNR state exceeds the bounded rule limit');

  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds:[...new Set(removeDnrIds)],
    addRules:normalized
  });
  await chrome.storage.local.set({[key]:newMap});
  return {ruleIds:normalized.map((rule) => newMap.find((item) => item.localId === rule.id)?.dnrId || rule.id)};
}

async function managementInstall(source, existing, allowUnsafeWorld) {
  const metadata = parseMetadata(source);
  const script = normalizeScript(source, metadata, existing, allowUnsafeWorld);
  if (metadata.world === 'MAIN' && !script.unsafeConfirmed) {
    throw new Error('unsafe userscript world requires explicit confirmation');
  }

  return serializeMutation(async () => {
    const current = await readScripts();
    const next = current.filter((item) => item.id !== script.id);
    next.push(script);
    await writeScripts(next);
    const registration = await registerOne(script);
    await syncMainWorldBridge(next);
    return {
      script:script,
      registration,
      requiredOrigins:matchOrigins(script.matches)
    };
  });
}

async function managementRemove(id) {
  return serializeMutation(async () => {
    const current = await readScripts();
    const existing = current.find((script) => script.id === id);
    if (!existing) return false;
    await userScriptsCall('unregister', {ids:[id]}).catch(() => {});
    const next = current.filter((script) => script.id !== id);
    await writeScripts(next);
    await syncMainWorldBridge(next);

    const all = await chrome.storage.local.get(null);
    const prefix = 'pasi:userscript:value:' + id + ':';
    const keys = Object.keys(all).filter((key) => key.startsWith(prefix));
    if (keys.length) await chrome.storage.local.remove(keys);
    return true;
  });
}

async function managementSetEnabled(id, enabled) {
  return serializeMutation(async () => {
    const current = await readScripts();
    const next = current.map((script) => script.id === id
      ? {...script, enabled:Boolean(enabled), updatedAt:new Date().toISOString()}
      : script);
    const updated = next.find((script) => script.id === id);
    if (!updated) throw new Error('unknown userscript: ' + id);
    await writeScripts(next);
    if (updated.enabled) await registerOne(updated);
    else await userScriptsCall('unregister', {ids:[id]}).catch(() => {});
    await syncMainWorldBridge(next);
    return updated;
  });
}

async function publicState() {
  const scripts = await readScripts();
  let registered = [];
  let apiError = null;
  try {
    registered = await userScriptsCall('getScripts');
  } catch (error) {
    apiError = String(error && error.message ? error.message : error);
  }
  return {
    apiAvailable:hasUserScriptsApi(),
    apiError,
    scripts:scripts.map(({token, source, ...rest}) => rest),
    registered:registered.map(({id, matches, runAt, world, worldId}) => ({id, matches, runAt, world, worldId}))
  };
}

async function runMenuCallback(menuId, tab) {
  if (!tab || !tab.id || !chrome.userScripts || typeof chrome.userScripts.execute !== 'function') return;
  const stored = await chrome.storage.session.get(MENU_STORE);
  const menus = Array.isArray(stored && stored[MENU_STORE]) ? stored[MENU_STORE] : [];
  const menu = menus.find((item) => item.id === menuId);
  if (!menu) return;
  const script = await scriptById(menu.scriptId);
  if (!script || !script.enabled) return;

  const callbackId = JSON.stringify(menuId);
  const code = '(() => { const callbacks = globalThis.__PASI_GM_MENU_CALLBACKS; if (callbacks && typeof callbacks[' +
    callbackId +
    '] === "function") callbacks[' +
    callbackId +
    '](); })();';
  const injection = {
    target:{tabId:tab.id},
    world:script.world,
    js:[{code}]
  };
  if (script.world === 'USER_SCRIPT') injection.worldId = 'pasi-us-' + script.id;
  await chrome.userScripts.execute(injection);
}

function tabMatchesScript(url, script) {
  try {
    const parsed = new URL(url);
    return script.matches.some((pattern) => {
      if (pattern === '<all_urls>') return true;
      const match = String(pattern).match(/^(\*|https?|file):\/\/([^/]+)(?:\/.*)?$/i);
      if (!match) return false;
      const schemeOk = match[1] === '*' || parsed.protocol === match[1] + ':';
      const hostPattern = match[2].toLowerCase();
      const host = parsed.hostname.toLowerCase();
      const hostOk = hostPattern === '*' ||
        (hostPattern.startsWith('*.') && host.endsWith(hostPattern.slice(1))) ||
        host === hostPattern;
      return schemeOk && hostOk;
    });
  } catch (_) {
    return false;
  }
}

async function reinstallIntoOpenTabs() {
  const scripts = await readScripts();
  for (const script of scripts) {
    if (!script.enabled) continue;
    await registerOne(script).catch((error) => console.warn('[PASI userscripts] register failed', error));
  }
  await syncMainWorldBridge(scripts);

  if (!chrome.tabs || !chrome.tabs.query || !chrome.userScripts || typeof chrome.userScripts.execute !== 'function') return;
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab.id || !tab.url) continue;
    for (const script of scripts) {
      if (!script.enabled) continue;
      if (!tabMatchesScript(tab.url, script)) continue;
      const injection = {
        target:{tabId:tab.id},
        world:script.world,
        js:[{code:createBootstrap(script)}]
      };
      if (script.world === 'USER_SCRIPT') injection.worldId = 'pasi-us-' + script.id;
      try {
        await chrome.userScripts.execute(injection);
      } catch (_) {
        // Normal for tabs whose URL is no longer eligible.
      }
    }
  }
}

if (chrome.runtime && chrome.runtime.onInstalled) {
  chrome.runtime.onInstalled.addListener((details) => {
    if (details.reason === 'install' || details.reason === 'update') {
      void reinstallIntoOpenTabs();
    }
  });
}

if (chrome.runtime && chrome.runtime.onStartup) {
  chrome.runtime.onStartup.addListener(() => void syncAll());
}

if (chrome.runtime && chrome.runtime.onUserScriptMessage) {
  chrome.runtime.onUserScriptMessage.addListener((message, sender, sendResponse) => {
    return sendRpcResponse(sendResponse, (async () => {
      const script = await authorizedScript(message);
      return rpc(script, message.op, message.data || {}, sender);
    })());
  });
}

if (chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message && message.source === 'pasi-userscript') {
      return sendRpcResponse(sendResponse, (async () => {
        const script = await authorizedScript(message);
        return rpc(script, message.op, message.data || {}, sender);
      })());
    }

    if (message && message.source === 'pasi-userscript-bridge') {
      return sendRpcResponse(sendResponse, (async () => {
        const script = await authorizedScript(message);
        if (script.world !== 'MAIN') throw new Error('bridge is only valid for MAIN world scripts');
        return rpc(script, message.op, message.data || {}, sender);
      })());
    }

    if (message && message.source === 'pasi-userscript-bridge-init') {
      const scriptsPromise = readScripts().then((scripts) =>
        scripts.filter((script) => script.enabled && script.world === 'MAIN')
          .map((script) => ({id:script.id, token:script.token}))
      );
      return sendRpcResponse(sendResponse, scriptsPromise);
    }

    if (message && message.source === 'pasi-userscript-management') {
      return sendRpcResponse(sendResponse, (async () => {
        if (message.op === 'install') {
          return managementInstall(message.sourceText, null, message.allowUnsafeWorld === true);
        }
        if (message.op === 'update') {
          const existing = await scriptById(message.id);
          if (!existing) throw new Error('unknown userscript: ' + message.id);
          return managementInstall(message.sourceText, existing, message.allowUnsafeWorld === true);
        }
        if (message.op === 'remove') return managementRemove(message.id);
        if (message.op === 'enable') return managementSetEnabled(message.id, true);
        if (message.op === 'disable') return managementSetEnabled(message.id, false);
        if (message.op === 'state') return publicState();
        throw new Error('unknown userscript management operation: ' + message.op);
      })());
    }

    return false;
  });
}

if (chrome.contextMenus && chrome.contextMenus.onClicked) {
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    void runMenuCallback(info.menuItemId, tab).catch((error) =>
      console.warn('[PASI userscripts] menu callback failed', error)
    );
  });
}

globalThis.PASI_USERSCRIPT_RUNTIME = Object.freeze({
  parseMetadata,
  normalizeScript,
  createBootstrap,
  connectAllowed,
  matchOrigins,
  managementInstall,
  managementRemove,
  managementSetEnabled,
  syncAll,
  publicState
});

globalThis.PASI_USERSCRIPT_RUNTIME_UTILS = Object.freeze({
  parseMetadata,
  normalizeScript,
  createBootstrap,
  connectAllowed,
  matchOrigins
});
