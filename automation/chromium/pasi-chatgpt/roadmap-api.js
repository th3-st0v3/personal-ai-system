(() => {
  'use strict';

  const request = (method, path, body = null, timeout = 60000) => new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: 'pasi-roadmap-request', method, path, body, timeout },
      (response) => {
        const error = chrome.runtime.lastError;
        if (error) { reject(new Error(error.message || 'roadmap extension messaging failed')); return; }
        if (!response || typeof response !== 'object') { reject(new Error('invalid roadmap bridge response')); return; }
        if (!response.ok) {
          let message = 'roadmap request failed (' + (response.status || 0) + ')';
          try {
            const payload = JSON.parse(response.text || '{}');
            if (payload?.error) message = String(payload.error);
          } catch (_) {}
          reject(new Error(message));
          return;
        }
        try { resolve(JSON.parse(response.text || 'null')); }
        catch (parseError) { reject(parseError); }
      }
    );
  });

  const PASI_ROADMAP_API = Object.freeze({
    list: () => request('GET', '/roadmaps'),
    active: () => request('GET', '/roadmap/active'),
    create: (name, rawText = '', tasks = []) => request('POST', '/roadmaps', { action: 'create', name, raw_text: rawText, tasks }),
    select: (roadmapId) => request('POST', '/roadmap/select', { roadmap_id: roadmapId }),
    archive: (roadmapId) => request('POST', '/roadmap/archive', { roadmap_id: roadmapId }),
    remove: (roadmapId) => request('POST', '/roadmap/delete', { roadmap_id: roadmapId }),
    combine: (roadmapIds, name) => request('POST', '/roadmap/combine', { roadmap_ids: roadmapIds, name }),
    saveTasks: (roadmapId, tasks, rawText = null) => request('POST', '/roadmap/tasks', { roadmap_id: roadmapId, tasks, ...(rawText === null ? {} : { raw_text: rawText }) }),
    dissect: (roadmapId, rawText, useCloud = true) => request('POST', '/roadmap/dissect', { roadmap_id: roadmapId, raw_text: rawText, use_cloud: useCloud }, 120000),
    nextPrompt: () => request('POST', '/roadmap/next-prompt', {}, 30000),
    enqueueNext: () => request('POST', '/roadmap/next-operation', {}, 30000)
  });

  globalThis.PASI_ROADMAP_API = PASI_ROADMAP_API;
})();