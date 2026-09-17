(() => {
  'use strict';

  const BRIDGE = 'http://127.0.0.1:8765';
  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const POLL_MS = 2000;
  const GENERATION_TIMEOUT_MS = 25 * 60 * 1000;
  const RECOVERY_TRIGGER_MS = GENERATION_TIMEOUT_MS;
  const RECOVERY_GRACE_MS = 10 * 60 * 1000;
  const MAX_RELOADS = 1;
  const MAX_NEW_CHAT_WAIT_MS = 30 * 1000;
  const RECOVERY_VERSION = '1.0.2';

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function bridge(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeout || 5000);
    try {
      const response = await fetch(BRIDGE + path, {
        method: options.method || 'GET',
        headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
        credentials: 'omit'
      });
      const text = await response.text();
      return { ok: response.ok, status: response.status, text, json: () => JSON.parse(text) };
    } finally {
      clearTimeout(timer);
    }
  }

  function activeOperationId() {
    try {
      if (typeof window.__PASI_CHATGPT_ACTIVE_OPERATION__ === 'function') {
        const value = window.__PASI_CHATGPT_ACTIVE_OPERATION__();
        if (value) return String(value);
      }
    } catch (_) {}
    try {
      const stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      return stored?.operation_id ? String(stored.operation_id) : null;
    } catch (_) {
      return null;
    }
  }

  function generating() {
    return Boolean(document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label*="Stop"]'));
  }

  function securityChallenge() {
    const text = normalize(document.body?.innerText || '');
    return ['verify you\'re human', 'captcha', 'cloudflare', 'security check', 'turnstile', 'session has expired', 'log in to continue', 'sign in to continue'].some((marker) => text.includes(marker));
  }

  function connectionFailure() {
    const text = normalize(document.body?.innerText || '');
    return ['network error', 'connection lost', 'failed to fetch', 'websocket', 'reconnecting'].some((marker) => text.includes(marker));
  }

  function contextExhausted() {
    const text = normalize(document.body?.innerText || '');
    return ['this conversation has reached its limit', 'conversation has reached its limit', 'conversation is too long', 'conversation is full', 'maximum conversation length', 'maximum length for this conversation', 'context limit reached', 'context window limit', 'context length limit', 'start a new chat to continue', 'start a new conversation to continue'].some((marker) => text.includes(marker));
  }

  function usageLimited() {
    if (contextExhausted()) return false;
    const text = normalize(document.body?.innerText || '');
    return ['current usage limit', 'usage limit reached', 'free tier limit', 'message limit', 'daily limit', 'weekly limit', 'model usage limit', 'rate limit', 'too many requests'].some((marker) => text.includes(marker));
  }

  function replacementReason() {
    if (contextExhausted()) return 'context_exhausted';
    if (usageLimited()) return 'usage_limited';
    return null;
  }

  function assistants() {
    return Array.from(document.querySelectorAll('[data-message-author-role="assistant"]')).filter((node) => {
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0;
    });
  }

  function latestAssistant() {
    const nodes = assistants();
    if (!nodes.length) return '';
    const node = nodes[nodes.length - 1];
    const markdown = Array.from(node.querySelectorAll?.('.markdown, [class*="markdown"]') || []);
    for (let index = markdown.length - 1; index >= 0; index -= 1) {
      const text = normalize(markdown[index].innerText || markdown[index].textContent || '');
      if (text) return text.slice(0, 50000);
    }
    return normalize(node.innerText || node.textContent || '').slice(0, 50000);
  }

  function fingerprint() { return latestAssistant().slice(-4000); }

  function readRecoveryState() {
    try {
      const value = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch (_) {
      return null;
    }
  }

  function writeRecoveryState(value) {
    localStorage.setItem(RECOVERY_KEY, JSON.stringify(value));
  }

  function clearRecoveryState() {
    localStorage.removeItem(RECOVERY_KEY);
  }

  async function operation(operationId) {
    try {
      const response = await bridge(`/operation?operation_id=${encodeURIComponent(operationId)}`);
      if (!response.ok) return null;
      const payload = response.json();
      return payload?.operation || null;
    } catch (_) {
      return null;
    }
  }

  async function report(kind, data = {}) {
    try {
      await bridge('/browser/observation', {
        method: 'POST',
        body: { observation: {
          schema_version: 'pasi-chatgpt-recovery-v2',
          captured_at: new Date().toISOString(),
          data: { kind, recovery_version: RECOVERY_VERSION, chat_url: location.href, ...data }
        } }
      });
    } catch (_) {}
  }

  async function finishExisting(operationId, responseText) {
    await report('chatgpt_response', {
      response_text: responseText.slice(0, 50000),
      response_text_available: Boolean(responseText),
      chat_exhausted: contextExhausted(),
      provider_usage_limited: usageLimited(),
      recovery_action: 'preserve_response'
    });
    const finished = await bridge('/chat/finished', {
      method: 'POST',
      body: { operation_id: operationId, chat_url: location.href, response_text_available: Boolean(responseText) }
    });
    return finished.ok;
  }

  async function markRetryableFailure(operationId, message) {
    try {
      const response = await bridge('/chat/failed', {
        method: 'POST',
        body: { operation_id: operationId, error: message }
      });
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  async function queueNewChat() {
    const response = await bridge('/queue', { method: 'POST', body: { operation_type: 'new_chat', prompt: '' } });
    if (!response.ok) throw new Error(`new_chat queue rejected with HTTP ${response.status}`);
    const payload = response.json();
    const newOperationId = payload?.operation?.operation_id;
    if (!newOperationId) throw new Error('new_chat queue did not return an operation id');
    const started = Date.now();
    while (Date.now() - started < MAX_NEW_CHAT_WAIT_MS) {
      const state = await operation(newOperationId);
      if (state?.status === 'completed') return newOperationId;
      if (state?.status === 'failed' || state?.status === 'cancelled') throw new Error(state.error || 'new_chat recovery operation failed');
      await sleep(500);
    }
    throw new Error('new_chat recovery operation did not finish within the recovery grace window');
  }

  async function preserveOrReload(operationId, state) {
    if (securityChallenge()) {
      await report('chatgpt_recovery', { phase: 'blocked_security_challenge', operation_id: operationId, recovery_action: 'manual_intervention_required' });
      return false;
    }

    const response = latestAssistant();
    const currentFingerprint = fingerprint();
    if (response && currentFingerprint !== String(state.baseline || '')) {
      if (await finishExisting(operationId, response)) {
        clearRecoveryState();
        return true;
      }
    }

    const startedMs = Number(state.started_ms || Date.now());
    const age = Date.now() - startedMs;
    const shouldRecover = connectionFailure() || age >= RECOVERY_TRIGGER_MS;
    if (shouldRecover && Number(state.reload_count || 0) < MAX_RELOADS) {
      const next = {
        ...state,
        reload_count: Number(state.reload_count || 0) + 1,
        phase: 'reloaded',
        reload_at: new Date().toISOString()
      };
      writeRecoveryState(next);
      await report('chatgpt_recovery', {
        phase: 'reloading',
        operation_id: operationId,
        recovery_action: 'reload_page',
        reload_count: next.reload_count,
        generation_timeout_ms: GENERATION_TIMEOUT_MS
      });
      location.reload();
      return true;
    }

    return false;
  }

  async function handleReloadRecovery(state) {
    const operationId = String(state.operation_id || '');
    if (!operationId) return;

    const current = await operation(operationId);
    if (current?.status === 'completed') {
      clearRecoveryState();
      return;
    }

    if (securityChallenge()) {
      await report('chatgpt_recovery', { phase: 'blocked_security_challenge', operation_id: operationId, recovery_action: 'manual_intervention_required' });
      await markRetryableFailure(operationId, 'CHAT_AUTH_REQUIRED: interactive authentication/security verification is required; PASI will not bypass it.');
      clearRecoveryState();
      return;
    }

    const response = latestAssistant();
    const currentFingerprint = fingerprint();
    if (response && currentFingerprint !== String(state.baseline || '')) {
      if (await finishExisting(operationId, response)) {
        clearRecoveryState();
        return;
      }
    }

    const reloadAt = Date.parse(String(state.reload_at || ''));
    if (Number.isFinite(reloadAt) && Date.now() - reloadAt < RECOVERY_GRACE_MS) {
      await report('chatgpt_recovery', {
        phase: 'grace_wait',
        operation_id: operationId,
        recovery_action: 'wait_after_reload',
        grace_remaining_ms: RECOVERY_GRACE_MS - (Date.now() - reloadAt)
      });
      return;
    }

    const reason = replacementReason();
    if (!reason) {
      await report('chatgpt_recovery', {
        phase: 'preserve_current_chat',
        operation_id: operationId,
        recovery_action: 'preserve_current_chat',
        reason: 'no_verified_usage_or_context_exhaustion'
      });
      await markRetryableFailure(operationId, 'PASI_NATIVE: browser page reloaded during operation; no verified usage/context exhaustion; current chat preserved for bounded retry.');
      clearRecoveryState();
      return;
    }

    try {
      await report('chatgpt_recovery', {
        phase: 'preparing_new_chat',
        operation_id: operationId,
        recovery_action: 'queue_new_chat',
        replacement_reason: reason
      });
      await queueNewChat();
      await markRetryableFailure(operationId, `CHAT_RECOVERED_RETRY: verified ${reason}; a fresh ChatGPT conversation was prepared for the same task.`);
      await report('chatgpt_recovery', {
        phase: 'ready_for_retry',
        operation_id: operationId,
        recovery_action: 'fresh_chat_prepared',
        replacement_reason: reason
      });
    } catch (error) {
      await markRetryableFailure(operationId, `CHAT_RECOVERY_FAILED: ${String(error?.message || error)}`);
      await report('chatgpt_recovery', { phase: 'failed', operation_id: operationId, recovery_action: 'retry_runner', error: String(error?.message || error) });
    }
    clearRecoveryState();
  }

  async function inspect() {
    const state = readRecoveryState();
    if (state?.operation_id) {
      await handleReloadRecovery(state);
      return;
    }

    const operationId = activeOperationId();
    if (!operationId) return;
    const current = await operation(operationId);
    if (!current || current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') return;

    const startedAt = current.created_at || current.updated_at || new Date().toISOString();
    const startedMs = Date.parse(startedAt);
    if (!Number.isFinite(startedMs)) return;
    const stateForTimer = {
      operation_id: operationId,
      started_ms: startedMs,
      baseline: fingerprint(),
      reload_count: 0,
      phase: 'monitoring'
    };

    const age = Date.now() - startedMs;
    if (age < RECOVERY_TRIGGER_MS && !connectionFailure()) return;
    await preserveOrReload(operationId, stateForTimer);
  }

  async function start() {
    await report('chatgpt_recovery', { phase: 'started', recovery_action: 'monitor', generation_timeout_ms: GENERATION_TIMEOUT_MS, recovery_grace_ms: RECOVERY_GRACE_MS });
    setInterval(() => { inspect().catch(() => {}); }, POLL_MS);
    await inspect();
  }

  start().catch(() => {});
})();
