(() => {
  'use strict';

  const BRIDGE = 'http://127.0.0.1:8765';
  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const RECOVERY_OPERATION_KEY = 'recovery_operation_id';
  const POLL_MS = 2000;
  const GENERATION_TIMEOUT_MS = 25 * 60 * 1000;
  const RECOVERY_TRIGGER_MS = GENERATION_TIMEOUT_MS;
  const RECOVERY_GRACE_MS = 10 * 60 * 1000;
  const MAX_RELOADS = 1;
  const MAX_NEW_CHAT_WAIT_MS = 30 * 1000;
  const MAX_CONTEXT_RECOVERIES = 1;
  const RECOVERY_VERSION = '1.0.5';

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
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
    return ['current usage limit', 'usage limit reached', 'free tier limit', 'message limit', 'daily limit', 'weekly limit', 'model usage limit'].some((marker) => text.includes(marker));
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
      const text = compact(markdown[index].innerText || markdown[index].textContent || '');
      if (text) return text.slice(0, 50000);
    }
    return compact(node.innerText || node.textContent || '').slice(0, 50000);
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
          schema_version: 'pasi-chatgpt-recovery-v3',
          captured_at: new Date().toISOString(),
          data: { kind, recovery_version: RECOVERY_VERSION, chat_url: location.href, ...data }
        } }
      });
    } catch (_) {}
  }

  async function finishExisting(operationId, responseText, knownChatUrl = '') {
    const bounded = responseText.slice(0, 50000);
    void report('chatgpt_response', {
      response_text: bounded,
      response_text_available: Boolean(bounded),
      chat_exhausted: contextExhausted(),
      provider_usage_limited: usageLimited(),
      recovery_action: 'preserve_response'
    });
    const body = {
      operation_id: operationId,
      chat_url: knownChatUrl || location.href,
      response_text: bounded,
      response_text_available: Boolean(bounded)
    };
    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const finished = await bridge('/chat/finished', { method: 'POST', body });
        if (finished.ok) return true;
        lastError = new Error(`bridge completion failed: HTTP ${finished.status}`);
      } catch (error) {
        lastError = error;
      }
      try {
        const current = await operation(operationId);
        if (current?.status === 'completed') return true;
      } catch (_) {}
      if (attempt < 3) await sleep(150);
    }
    await report('chatgpt_recovery', { phase: 'completion_ack_failed', operation_id: operationId, recovery_action: 'retry_runner', error: String(lastError?.message || lastError || 'unknown error') });
    return false;
  }

  function recoveryContextFromActiveState() {
    try {
      const stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      if (!stored || typeof stored !== 'object') return null;
      const context = {};
      if (stored.reasoning_mode === 'thinking') context.reasoning_mode = 'thinking';
      const repository = typeof stored.github_repository === 'string'
        ? stored.github_repository.trim()
        : '';
      if (repository && repository.length <= 200 && /^[^/\s]+\/[^/\s]+$/.test(repository)) {
        context.github_repository = repository;
      }
      return Object.keys(context).length ? context : null;
    } catch (_) {
      return null;
    }
  }

  async function markRetryableFailure(operationId, message, recoveryContext = null) {
    try {
      const body = { operation_id: operationId, error: message };
      if (recoveryContext) body.recovery_context = recoveryContext;
      const response = await bridge('/chat/failed', {
        method: 'POST',
        body
      });
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  function persistedResponse(current) {
    const text = current?.response_text;
    return (
      current?.response_text_available === true &&
      typeof text === 'string' &&
      Boolean(text.trim())
    ) ? text : '';
  }

  async function finishPersistedResponse(current) {
    const response = persistedResponse(current);
    if (!response) return false;
    const knownChatUrl = typeof current.chat_url === 'string' ? current.chat_url : '';
    return finishExisting(current.operation_id, response, knownChatUrl);
  }

  function clearInterruptedState() {
    clearRecoveryState();
    localStorage.removeItem(ACTIVE_KEY);
  }

  async function handleContextExhausted(state) {
    const operationId = String(state.operation_id || '');
    if (!operationId) return;

    const current = await operation(operationId);
    if (!current) return;

    if (current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') {
      clearInterruptedState();
      return;
    }

    if (current.operation_type !== 'prompt') {
      await report('chatgpt_recovery', {
        phase: 'context_recovery_skipped',
        operation_id: operationId,
        recovery_action: 'preserve_current_chat',
        reason: 'unsupported_operation_type'
      });
      return;
    }

    if (await finishPersistedResponse(current)) {
      clearInterruptedState();
      return;
    }

    if (securityChallenge()) {
      await report('chatgpt_recovery', {
        phase: 'blocked_security_challenge',
        operation_id: operationId,
        recovery_action: 'manual_intervention_required'
      });
      return;
    }

    if (Number(current.retry_count || 0) >= MAX_CONTEXT_RECOVERIES) {
      await report('chatgpt_recovery', {
        phase: 'context_recovery_budget_exhausted',
        operation_id: operationId,
        recovery_action: 'retry_runner',
        retry_count: Number(current.retry_count || 0)
      });
      return;
    }

    if (!contextExhausted()) {
      await report('chatgpt_recovery', {
        phase: 'context_recovery_waiting',
        operation_id: operationId,
        recovery_action: 'wait_for_verified_exhaustion'
      });
      return;
    }

    try {
      await report('chatgpt_recovery', {
        phase: 'preparing_new_chat',
        operation_id: operationId,
        recovery_action: 'queue_new_chat',
        replacement_reason: 'context_exhausted'
      });
      const recoveryContext = state.recovery_context || recoveryContextFromActiveState();
      await queueNewChat();

      const beforeRetry = await operation(operationId);
      if (beforeRetry?.status !== 'completed' && beforeRetry?.status !== 'failed' && beforeRetry?.status !== 'cancelled') {
        const accepted = await markRetryableFailure(
          operationId,
          'CHAT_EXHAUSTED: verified conversation context exhaustion; a fresh chat was prepared for the same operation.',
          recoveryContext
        );
        const afterRetry = await operation(operationId);
        if (!accepted && afterRetry?.status !== 'queued') {
          throw new Error('original context-exhausted operation was not requeued');
        }
        if (afterRetry?.status === 'queued') {
          clearInterruptedState();
          await report('chatgpt_recovery', {
            phase: 'ready_for_retry',
            operation_id: operationId,
            recovery_action: 'fresh_chat_prepared',
            replacement_reason: 'context_exhausted',
            retry_count: Number(afterRetry.retry_count || 0)
          });
          return;
        }
      }

      if (beforeRetry?.status === 'completed' || beforeRetry?.status === 'failed' || beforeRetry?.status === 'cancelled') {
        clearInterruptedState();
      }
    } catch (error) {
      await report('chatgpt_recovery', {
        phase: 'failed',
        operation_id: operationId,
        recovery_action: 'retry_runner',
        error: String(error?.message || error)
      });
    }
  }

  async function queueNewChat() {
    const response = await bridge('/queue', { method: 'POST', body: { operation_type: 'new_chat', prompt: '' } });
    if (!response.ok) throw new Error(`new_chat queue rejected with HTTP ${response.status}`);
    const payload = response.json();
    const newOperationId = payload?.operation?.operation_id;
    if (!newOperationId) throw new Error('new_chat queue did not return an operation id');
    const recoveryState = readRecoveryState();
    if (recoveryState) {
      writeRecoveryState({ ...recoveryState, [RECOVERY_OPERATION_KEY]: newOperationId });
    }
    const started = Date.now();
    while (Date.now() - started < MAX_NEW_CHAT_WAIT_MS) {
      const state = await operation(newOperationId);
      if (state?.status === 'completed') {
        const latestRecoveryState = readRecoveryState();
        if (latestRecoveryState) {
          const nextState = { ...latestRecoveryState };
          delete nextState[RECOVERY_OPERATION_KEY];
          writeRecoveryState(nextState);
        }
        return newOperationId;
      }
      if (state?.status === 'failed' || state?.status === 'cancelled') throw new Error(state.error || 'new_chat recovery operation failed');
      await sleep(500);
    }
    throw new Error('new_chat recovery operation did not finish within the recovery grace window');
  }

  async function preserveOrReload(operationId, state) {
    const current = await operation(operationId);
    if (!current) return false;

    if (securityChallenge()) {
      await report('chatgpt_recovery', { phase: 'blocked_security_challenge', operation_id: operationId, recovery_action: 'manual_intervention_required' });
      return false;
    }

    if (await finishPersistedResponse(current)) {
      clearInterruptedState();
      return;
    }

    const response = latestAssistant();
    const currentFingerprint = fingerprint();
    if (response && currentFingerprint !== String(state.baseline || '')) {
      if (await finishExisting(operationId, response, typeof current.chat_url === 'string' ? current.chat_url : '')) {
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
        recovery_context: state.recovery_context || recoveryContextFromActiveState(),
        reload_count: Number(state.reload_count || 0) + 1,
        phase: 'reloaded',
        reload_at: new Date().toISOString()
      };
      writeRecoveryState(next);
      await report('chatgpt_recovery', { phase: 'reloading', operation_id: operationId, recovery_action: 'reload_page', reload_count: next.reload_count, generation_timeout_ms: GENERATION_TIMEOUT_MS });
      location.reload();
      return true;
    }

    return false;
  }

  async function handleReloadRecovery(state) {
    const operationId = String(state.operation_id || '');
    if (!operationId) return;

    const current = await operation(operationId);
    if (current?.status === 'completed' || current?.status === 'failed' || current?.status === 'cancelled') {
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
      await report('chatgpt_recovery', { phase: 'grace_wait', operation_id: operationId, recovery_action: 'wait_after_reload', grace_remaining_ms: RECOVERY_GRACE_MS - (Date.now() - reloadAt) });
      return;
    }

    const recoveryContext = state.recovery_context || recoveryContextFromActiveState();
    const reason = replacementReason();
    if (!reason) {
      await report('chatgpt_recovery', { phase: 'preserve_current_chat', operation_id: operationId, recovery_action: 'preserve_current_chat', reason: 'no_verified_usage_or_context_exhaustion' });
      await markRetryableFailure(
        operationId,
        'PASI_NATIVE: browser page reloaded during operation; no verified usage/context exhaustion; current chat preserved for bounded retry.',
        recoveryContext
      );
      clearRecoveryState();
      return;
    }

    try {
      await report('chatgpt_recovery', { phase: 'preparing_new_chat', operation_id: operationId, recovery_action: 'queue_new_chat', replacement_reason: reason });
      await queueNewChat();
      const accepted = await markRetryableFailure(
        operationId,
        `CHAT_RECOVERED_RETRY: verified ${reason}; a fresh ChatGPT conversation was prepared for the same task.`,
        recoveryContext
      );
      const afterRetry = await operation(operationId);
      if (!accepted || afterRetry?.status !== 'queued') {
        await report('chatgpt_recovery', {
          phase: 'retry_requeue_not_verified',
          operation_id: operationId,
          recovery_action: 'retry_runner',
          replacement_reason: reason
        });
        clearRecoveryState();
        return;
      }
      const latestRecoveryState = readRecoveryState();
      if (latestRecoveryState) {
        writeRecoveryState({
          ...latestRecoveryState,
          resume_operation_id: operationId,
          phase: 'retry_ready'
        });
      }
      await report('chatgpt_recovery', { phase: 'ready_for_retry', operation_id: operationId, recovery_action: 'fresh_chat_prepared', replacement_reason: reason });
    } catch (error) {
      await markRetryableFailure(operationId, `CHAT_RECOVERY_FAILED: ${String(error?.message || error)}`);
      await report('chatgpt_recovery', { phase: 'failed', operation_id: operationId, recovery_action: 'retry_runner', error: String(error?.message || error) });
    }
    if (readRecoveryState()?.resume_operation_id === operationId) return;
    clearRecoveryState();
  }

  async function inspect() {
    const state = readRecoveryState();
    if (state?.operation_id) {
      if (state.phase === 'context_exhausted') {
        await handleContextExhausted(state);
        return;
      }

      const current = await operation(state.operation_id);
      if (!current || current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') {
        clearInterruptedState();
        return;
      }

      if (state.phase === 'monitoring') {
        const startedMs = Number(state.started_ms || Date.parse(current.created_at || '') || Date.now());
        if (Date.now() - startedMs < RECOVERY_TRIGGER_MS && !connectionFailure()) return;
        await preserveOrReload(state.operation_id, state);
        return;
      }

      await handleReloadRecovery(state);
      return;
    }

    const operationId = activeOperationId();
    if (!operationId) return;
    const current = await operation(operationId);
    if (!current || current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') return;

    if (await finishPersistedResponse(current)) {
      clearInterruptedState();
      return;
    }

    const startedAt = current.created_at || current.updated_at || new Date().toISOString();
    const startedMs = Date.parse(startedAt);
    if (!Number.isFinite(startedMs)) return;

    const stateForTimer = {
      operation_id: operationId,
      started_ms: startedMs,
      baseline: fingerprint(),
      reload_count: 0,
      phase: 'monitoring',
      chat_url: typeof current.chat_url === 'string' ? current.chat_url : location.href,
      recovery_context: recoveryContextFromActiveState()
    };
    writeRecoveryState(stateForTimer);

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
