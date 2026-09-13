(() => {
  'use strict';

  const listeners = new Map();
  const state = Object.create(null);
  const MODEL_VALUE_TO_PROFILE = {
    auto: 'profile:auto',
    claude: 'profile:claude-opus',
    gpt: 'profile:gpt-5.4',
    gemini: 'profile:gemini-3.1-pro',
    free: 'profile:free',
  };

  const emit = (event, detail) => {
    const handlers = listeners.get(event) || [];
    handlers.forEach((handler) => {
      try { handler(detail); } catch (error) { console.error('PASRuntime listener error', error); }
    });
    window.dispatchEvent(new CustomEvent(`pas:${event}`, { detail }));
  };

  window.PASRuntime = Object.freeze({
    get(key) { return state[key]; },
    set(key, value) { state[key] = value; emit('state', { key, value }); return value; },
    patch(values) { Object.entries(values || {}).forEach(([key, value]) => { state[key] = value; }); emit('state', { patch: { ...(values || {}) } }); },
    on(event, handler) {
      if (typeof handler !== 'function') throw new TypeError('handler must be a function');
      const handlers = listeners.get(event) || [];
      handlers.push(handler);
      listeners.set(event, handlers);
      return () => listeners.set(event, handlers.filter((item) => item !== handler));
    },
    emit,
  });

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const requestInit = { credentials: 'same-origin', ...init };
    const url = typeof input === 'string' ? input : input?.url || '';
    if (requestInit.body && String(url).includes('/api/chats/') && String(url).endsWith('/messages')) {
      try {
        const payload = JSON.parse(String(requestInit.body));
        if (typeof payload.model === 'string' && MODEL_VALUE_TO_PROFILE[payload.model]) {
          payload.model = MODEL_VALUE_TO_PROFILE[payload.model];
          requestInit.body = JSON.stringify(payload);
        }
        // Explicitly surface the chosen mode in the API contract even though
        // the existing composer did not send one.
        if (!payload.mode) payload.mode = 'auto';
        requestInit.body = JSON.stringify(payload);
      } catch (_) {
        // Leave non-JSON requests untouched; the API layer will validate them.
      }
    }
    const response = await nativeFetch(input, requestInit);
    if (response.ok) return response;

    let message = `Request failed (${response.status})`;
    let payload = null;
    try {
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        payload = await response.clone().json();
        if (payload && typeof payload.error === 'string') message = payload.error;
      }
    } catch (_) {}
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    emit('api-error', error);
    throw error;
  };

  // ``app.js`` currently references the legacy global `event` in one file
  // click handler. Capture the real event so the legacy handler has a stable
  // value without altering its surrounding UI behavior.
  document.addEventListener('click', (event) => {
    try { window.event = event; } catch (_) {}
  }, true);

  window.addEventListener('error', (event) => {
    emit('runtime-error', { message: event.message, filename: event.filename, lineno: event.lineno });
  });
  window.addEventListener('unhandledrejection', (event) => {
    emit('runtime-error', { message: String(event.reason?.message || event.reason || 'Unhandled promise rejection') });
  });
})();
