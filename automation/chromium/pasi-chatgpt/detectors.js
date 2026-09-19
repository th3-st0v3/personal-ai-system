(() => {
  'use strict';

  const SCOPED_SELECTORS = [
    '[role="alert"]',
    '[role="status"]',
    '[aria-live="assertive"]',
    '[aria-live="polite"]',
    '[data-testid*="toast" i]',
    '[data-testid*="banner" i]',
    '[data-radix-toast-viewport]'
  ];

  const CONTEXT_MARKERS = [
    'this conversation has reached its limit',
    'conversation has reached its limit',
    'conversation limit reached',
    'conversation is too long',
    'conversation is full',
    'maximum conversation length',
    'maximum length for this conversation',
    'context limit reached',
    'context window limit',
    'context length limit',
    'start a new chat to continue',
    'start a new conversation to continue'
  ];

  const USAGE_MARKERS = [
    'current usage limit',
    'usage limit reached',
    'free tier limit',
    'message limit',
    'daily limit',
    'weekly limit',
    'model usage limit',
    'rate limit',
    'too many requests'
  ];

  const AUTH_MARKERS = [
    'log in to continue',
    'sign in to continue',
    "verify you're human",
    'security check',
    'captcha',
    'session has expired',
    'cloudflare',
    'turnstile'
  ];

  const CONNECTION_MARKERS = [
    'network error',
    'connection lost',
    'failed to fetch',
    'reconnecting'
  ];

  function normalize(value) {
    return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function excluded(element) {
    return Boolean(element?.closest?.(
      '[data-message-author-role], nav, aside, [role="navigation"], [data-testid*="sidebar" i]'
    ));
  }

  function scopedTexts() {
    const values = [];
    const seen = new Set();
    for (const selector of SCOPED_SELECTORS) {
      for (const element of document.querySelectorAll(selector)) {
        if (seen.has(element) || excluded(element)) continue;
        seen.add(element);
        const text = normalize(element.innerText || element.textContent || '');
        if (text) values.push(text);
      }
    }
    return values;
  }

  function contains(markers, values) {
    return values.some((text) => markers.some((marker) => text.includes(marker)));
  }

  function detect() {
    const texts = scopedTexts();
    return {
      context_exhausted: contains(CONTEXT_MARKERS, texts),
      usage_limited: contains(USAGE_MARKERS, texts),
      auth_required: contains(AUTH_MARKERS, texts),
      connection_failure: contains(CONNECTION_MARKERS, texts),
      scope_count: texts.length
    };
  }

  globalThis.PASIChatGPTDetectors = Object.freeze({
    detect,
    contextExhausted() { return detect().context_exhausted; },
    usageLimited() {
      const result = detect();
      return !result.context_exhausted && result.usage_limited;
    },
    authRequired() { return detect().auth_required; },
    connectionFailure() { return detect().connection_failure; }
  });
})();
