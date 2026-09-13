(() => {
  'use strict';

  const listeners = new Map();
  const state = Object.create(null);

  const emit = (event, detail) => {
    const handlers = listeners.get(event) || [];
    handlers.forEach((handler) => {
      try { handler(detail); } catch (error) { console.error('PASRuntime listener error', error); }
    });
    window.dispatchEvent(new CustomEvent(`pas:${event}`, { detail }));
  };

  window.PASRuntime = Object.freeze({
    get(key) { return state[key]; },
    set(key, value) {
      state[key] = value;
      emit('state', { key, value });
      return value;
    },
    patch(values) {
      Object.entries(values || {}).forEach(([key, value]) => { state[key] = value; });
      emit('state', { patch: { ...(values || {}) } });
    },
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
    } catch (_) {
      // Preserve the HTTP-status error when the response body is malformed.
    }
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    emit('api-error', error);
    throw error;
  };

  window.addEventListener('error', (event) => {
    emit('runtime-error', { message: event.message, filename: event.filename, lineno: event.lineno });
  });
  window.addEventListener('unhandledrejection', (event) => {
    emit('runtime-error', { message: String(event.reason?.message || event.reason || 'Unhandled promise rejection') });
  });
})();
