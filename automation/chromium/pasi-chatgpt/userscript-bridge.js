/* global chrome */
'use strict';

(() => {
  const configs = new Map();
  let initialized = false;

  function postResponse(requestId, ok, result, error) {
    window.postMessage({
      source: 'pasi-userscript-main-response',
      requestId,
      ok,
      result,
      error
    }, location.origin);
  }

  function extensionAlive() {
    try {
      return Boolean(chrome.runtime && chrome.runtime.id);
    } catch (_) {
      return false;
    }
  }

  async function initialize() {
    if (initialized) return;
    initialized = true;
    if (!extensionAlive()) return;
    try {
      const response = await chrome.runtime.sendMessage({
        source: 'pasi-userscript-bridge-init'
      });
      if (response && response.ok && Array.isArray(response.result)) {
        for (const item of response.result) {
          if (item && item.id && item.token) configs.set(item.id, item.token);
        }
      }
    } catch (_) {
      initialized = false;
    }
  }

  window.addEventListener('message', (event) => {
    const message = event.data;
    if (!message || message.source !== 'pasi-userscript-main') return;
    void (async () => {
      await initialize();
      if (!configs.has(message.scriptId) || configs.get(message.scriptId) !== message.token) {
        postResponse(message.requestId, false, undefined, 'PASI userscript bridge authentication failed');
        return;
      }
      if (!extensionAlive()) {
        postResponse(message.requestId, false, undefined, 'PASI userscript extension context invalidated');
        return;
      }

      try {
        const response = await chrome.runtime.sendMessage({
          source: 'pasi-userscript-bridge',
          scriptId: message.scriptId,
          token: message.token,
          op: message.op,
          data: message.data || {}
        });
        if (!response || response.ok !== true) {
          postResponse(message.requestId, false, undefined, response && response.error || 'PASI userscript bridge request failed');
          return;
        }
        postResponse(message.requestId, true, response.result, undefined);
      } catch (error) {
        postResponse(message.requestId, false, undefined, String(error && error.message ? error.message : error));
      }
    })();
  });

  void initialize();
})();
