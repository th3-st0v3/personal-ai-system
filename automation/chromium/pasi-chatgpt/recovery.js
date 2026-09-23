(() => {
  'use strict';

  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const RECOVERY_OPERATION_KEY = 'recovery_operation_id';
  const TIMEOUT_POLICY = globalThis.PASI_TIMEOUT_POLICY?.get?.() || {};
  const RECOVERY_PROGRESS = globalThis.PASI_RECOVERY_PROGRESS;
  const POLL_MS = TIMEOUT_POLICY.pollMs || 500;
  const GENERATION_TIMEOUT_MS = TIMEOUT_POLICY.generationMs || 60 * 60 * 1000;
  const RECOVERY_TRIGGER_MS = TIMEOUT_POLICY.recoveryTriggerMs || GENERATION_TIMEOUT_MS;
  const RECOVERY_GRACE_MS = TIMEOUT_POLICY.recoveryGraceMs || 10 * 60 * 1000;
  const RECOVERY_STALL_MS = TIMEOUT_POLICY.recoveryStallMs || 8 * 60 * 1000;
  const RECOVERY_HARD_CEILING_MS = TIMEOUT_POLICY.recoveryHardCeilingMs || 90 * 60 * 1000;
  const RECOVERY_PROGRESS_SAMPLE_MS = TIMEOUT_POLICY.recoveryProgressSampleMs || 250;
  const RECOVERY_PROGRESS_POLL_MS = TIMEOUT_POLICY.recoveryProgressPollMs || 5000;
  const MAX_RELOADS = 1;
  const MAX_NEW_CHAT_WAIT_MS = 30 * 1000;
  const MAX_CONTEXT_RECOVERIES = 1;
  const MISSING_OPERATION_GRACE_MS = 60 * 1000;
  const MISSING_OPERATION_REPORT_MS = 10 * 1000;
  const RECOVERY_VERSION = '1.0.6';
  const MAX_RESPONSE_TEXT_CHARS = 120_000;
  let inspecting = false;
  let progressTracker = null;
  let progressOperationId = null;
  let progressObserverHandle = null;
  const progressNodeIds = new WeakMap();
  let nextProgressNodeId = 1;
  let lastProgressPersistMs = 0;

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function bridge(path, options = {}) {
    if (!globalThis.chrome?.runtime?.sendMessage) {
      throw new Error('PASI_NATIVE: extension messaging API unavailable');
    }
    const timeoutMs = Number(options.timeout || 5000);
    return new Promise((resolve, reject) => {
      let settled = false;
      const timerId = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error('PASI_NATIVE: bridge message timed out'));
      }, timeoutMs);
      try {
        chrome.runtime.sendMessage({
          type: 'pasi-bridge-request',
          path: String(path || ''),
          method: String(options.method || 'GET').toUpperCase(),
          body: options.body ?? null
        }, (response) => {
          if (settled) return;
          settled = true;
          clearTimeout(timerId);
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError) {
            reject(new Error('PASI_NATIVE: extension bridge error: ' + runtimeError.message));
            return;
          }
          if (!response || typeof response !== 'object') {
            reject(new Error('PASI_NATIVE: invalid bridge response'));
            return;
          }
          const text = typeof response.text === 'string' ? response.text : '';
          const error = typeof response.error === 'string' ? response.error : '';
          resolve({
            ok: response.ok === true,
            status: Number(response.status || 0),
            text,
            error,
            json: () => JSON.parse(text)
          });
        });
      } catch (error) {
        if (settled) return;
        settled = true;
        clearTimeout(timerId);
        reject(error);
      }
    });
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

  function recoveryContextFromActiveState() {
    try {
      const stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      const context = stored?.recovery_context;
      if (!context || typeof context !== 'object') return null;

      const normalized = {};
      if (typeof context.reasoning_mode === 'string') {
        const mode = context.reasoning_mode.trim().toLowerCase();
        if (mode === 'thinking' || mode === 'think') normalized.reasoning_mode = 'thinking';
      }
      if (typeof context.github_repository === 'string') {
        const repository = context.github_repository.trim();
        if (/^[^/\\s]+\/[^/\\s]+$/.test(repository) && repository.length <= 200) {
          normalized.github_repository = repository;
        }
      }
      return Object.keys(normalized).length ? normalized : null;
    } catch (_) {
      return null;
    }
  }

  function generating() {
    return Boolean(document.querySelector('button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label*="Stop"]'));
  }

  function securityChallenge() {
    const text = normalize(document.body?.innerText || '');
    return ["verify you're human", 'captcha', 'cloudflare', 'security check', 'turnstile', 'session has expired', 'log in to continue', 'sign in to continue'].some((marker) => text.includes(marker));
  }

  function visibleElement(element) {
    if (!element) return false;
    try {
      const style = getComputedStyle(element);
      return style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        element.getClientRects().length > 0;
    } catch (_) {
      return false;
    }
  }

  function connectionFailure() {
    const selectors = [
      '[role="alert"]',
      '[aria-live="assertive"]',
      '[data-testid*="error" i]',
      '[data-testid*="connection" i]',
      '[data-testid*="network" i]',
      '[class*="error" i]',
      '[class*="connection" i]',
      '[class*="network" i]'
    ];
    const markers = ['network error', 'connection lost', 'failed to fetch', 'websocket error', 'reconnecting', 'connection error'];
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!visibleElement(element)) continue;
        const text = normalize(element.innerText || element.textContent || '');
        if (markers.some((marker) => text.includes(marker))) return true;
      }
    }
    return false;
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
      if (text) return text.slice(0, MAX_RESPONSE_TEXT_CHARS);
    }
    return compact(node.innerText || node.textContent || '').slice(0, MAX_RESPONSE_TEXT_CHARS);
  }

  function promptFingerprints(prompt) {
    const text = normalize(prompt);
    return { head: text.slice(0, 80), tail: text.slice(-80) };
  }

  function userMessages() {
    return Array.from(document.querySelectorAll('[data-message-author-role="user"]')).filter(visibleElement);
  }

  function nodeFollows(earlier, later) {
    if (!earlier || !later || typeof earlier.compareDocumentPosition !== 'function') return false;
    return Boolean(earlier.compareDocumentPosition(later) & 4);
  }

  function userMessageMatchesOperation(node, operation) {
    if (!node || !operation) return false;
    const prefix = '[PASI_OPERATION ' + String(operation.operation_id || '') + ']';
    const prompt = typeof operation.prompt === 'string' && operation.prompt.trim()
      ? prefix + '\\n' + operation.prompt
      : prefix;
    const text = normalize(node.innerText || node.textContent || '');
    const { head, tail } = promptFingerprints(prompt);
    return Boolean((head && text.includes(head)) || (tail && text.includes(tail)));
  }

  function latestAssistantForOperation(operation) {
    if (!operation) return '';
    const matchedUsers = userMessages().filter((node) => userMessageMatchesOperation(node, operation));
    if (!matchedUsers.length) return '';

    const nodes = assistants();
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const node = nodes[index];
      if (!matchedUsers.some((user) => nodeFollows(user, node))) continue;
      const text = compact(node.innerText || node.textContent || '');
      if (!text) continue;
      return text.slice(0, MAX_RESPONSE_TEXT_CHARS);
    }
    return '';
  }

  function fingerprint() { return latestAssistant().slice(-4000); }

  function progressNodeId(node) {
    if (!node || typeof node !== 'object') return null;
    let id = progressNodeIds.get(node);
    if (!id) {
      id = 'assistant-' + String(nextProgressNodeId++);
      progressNodeIds.set(node, id);
    }
    return id;
  }

  function latestAssistantNode() {
    const nodes = assistants();
    return nodes.length ? nodes[nodes.length - 1] : null;
  }

  function assistantProgressIndicator(node) {
    if (!node) return '';
    const selectors = [
      '[role="status"]',
      '[aria-live]',
      '[data-testid*="thinking" i]',
      '[data-testid*="reason" i]',
      '[data-testid*="status" i]',
      '[class*="thinking" i]',
      '[class*="reason" i]'
    ];
    for (const selector of selectors) {
      for (const element of node.querySelectorAll?.(selector) || []) {
        if (!visibleElement(element)) continue;
        const text = compact(element.innerText || element.textContent || '');
        if (text && text.length <= 300) return text;
      }
    }
    return '';
  }

  function assistantProgressSample() {
    const node = latestAssistantNode();
    if (!node) return null;
    const text = compact(node.innerText || node.textContent || '');
    return {
      nodeId: progressNodeId(node),
      length: Math.min(text.length, MAX_RESPONSE_TEXT_CHARS),
      indicator: assistantProgressIndicator(node)
    };
  }

  function seedProgressTracker(state) {
    if (!RECOVERY_PROGRESS?.ProgressTracker) return null;
    const startedMs = Number(state?.started_ms || Date.now());
    const lastProgressMs = Number(state?.last_progress_ms || startedMs);
    const tracker = new RECOVERY_PROGRESS.ProgressTracker(
      Number.isFinite(lastProgressMs) ? lastProgressMs : startedMs
    );
    const sample = assistantProgressSample();
    if (sample) {
      tracker.nodeId = sample.nodeId;
      tracker.maxLength = sample.length;
      tracker.indicator = RECOVERY_PROGRESS.normalizeIndicator(sample.indicator);
    }
    return tracker;
  }

  function beginProgressTracking(operationId, state) {
    if (!RECOVERY_PROGRESS?.ProgressTracker) return;
    if (progressOperationId === operationId && progressTracker) return;
    progressOperationId = operationId;
    progressTracker = seedProgressTracker(state);
  }

  function persistProgressState(state) {
    if (!progressTracker || !state) return;
    const now = Date.now();
    if (now - lastProgressPersistMs < 1000) return;
    lastProgressPersistMs = now;
    writeRecoveryState({
      ...state,
      last_progress_ms: progressTracker.lastProgressMs,
      progress_node_id: progressTracker.nodeId,
      progress_max_length: progressTracker.maxLength,
      progress_indicator: progressTracker.indicator || ''
    });
  }

  function sampleProgress(state) {
    if (!RECOVERY_PROGRESS?.ProgressTracker || !state?.operation_id) return;
    beginProgressTracking(state.operation_id, state);
    const sample = assistantProgressSample();
    if (!sample || !progressTracker) return;
    progressTracker.observe(sample, Date.now());
    persistProgressState(state);
  }

  function recoveryProgressConfig() {
    if (!RECOVERY_PROGRESS?.resolveRecoveryConfig) return null;
    try {
      return RECOVERY_PROGRESS.resolveRecoveryConfig({
        stallMs: RECOVERY_STALL_MS,
        hardCeilingMs: RECOVERY_HARD_CEILING_MS,
        sampleThrottleMs: RECOVERY_PROGRESS_SAMPLE_MS,
        backstopPollMs: RECOVERY_PROGRESS_POLL_MS,
        maxReloads: MAX_RELOADS
      });
    } catch (_) {
      return null;
    }
  }

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
    progressOperationId = null;
    progressTracker = null;
  }

  function recoveryCompletionFields(state, outcome) {
    const finishedAtMs = Date.now();
    const startedAtMs = Number(state?.recovery_started_at_ms || 0);
    return {
      recovery_finished_at_ms: finishedAtMs,
      ...(Number.isFinite(startedAtMs) && startedAtMs > 0
        ? { recovery_duration_ms: Math.max(0, finishedAtMs - startedAtMs) }
        : {}),
      recovery_reason: state?.recovery_reason || 'page_reload',
      outcome
    };
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

  async function finishExisting(operationId, responseText) {
    const bounded = String(responseText || '').slice(0, MAX_RESPONSE_TEXT_CHARS);
    const available = Boolean(bounded.trim());
    if (!available) return false;

    await report('chatgpt_response', {
      active_operation_id: operationId,
      response_text: bounded,
      response_text_available: true,
      chat_exhausted: contextExhausted(),
      recovery_action: 'preserve_response'
    });

    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const finished = await bridge('/chat/finished', {
          method: 'POST',
          body: {
            operation_id: operationId,
            chat_url: location.href,
            response_text: bounded,
            response_text_available: true
          }
        });
        if (finished.ok) return true;
        const acknowledged = await operation(operationId);
        if (
          acknowledged?.status === 'completed' &&
          acknowledged?.response_text_available === true &&
          typeof acknowledged?.response_text === 'string' &&
          Boolean(acknowledged.response_text.trim())
        ) {
          return true;
        }
        lastError = new Error(`bridge completion failed: HTTP ${finished.status}`);
      } catch (error) {
        lastError = error;
      }
      if (attempt < 3) await sleep(Math.min(POLL_MS, 500));
    }
    await report('chatgpt_recovery', {
      phase: 'completion_ack_failed',
      operation_id: operationId,
      recovery_action: 'retry_runner',
      error: String(lastError?.message || lastError || 'unknown completion acknowledgement failure')
    });
    return false;
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
    return finishExisting(current.operation_id, response);
  }

  function clearInterruptedState() {
    clearRecoveryState();
    localStorage.removeItem(ACTIVE_KEY);
  }

  async function finishVisibleResponse(operationId, current, baseline) {
    if (!current || current.operation_type !== 'prompt') return false;
    if (await finishPersistedResponse(current)) return true;
    const response = latestAssistantForOperation(current);
    if (generating() || !response) return false;
    return finishExisting(operationId, response);
  }

  async function handleContextExhausted(state) {
    const operationId = String(state.operation_id || '');
    if (!operationId) return;

    const current = await operation(operationId);
    if (!current) return;

    if (current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') {
      if (await finishVisibleResponse(operationId, current, state.baseline)) {
        clearInterruptedState();
        return;
      }
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
            retry_count: Number(afterRetry.retry_count || 0),
            ...recoveryCompletionFields(state, 'resumed')
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

    if (usageLimited()) {
      await report('chatgpt_recovery', { phase: 'usage_limited', operation_id: operationId, recovery_action: 'retry_runner_after_provider_limit' });
      await markRetryableFailure(operationId, 'CHAT_USAGE_LIMITED: ChatGPT reported a usage limit; PASI will not delete or replace the conversation solely because usage is exhausted.');
      clearRecoveryState();
      return;
    }

    const response = latestAssistant();
    const currentFingerprint = fingerprint();
    if (!generating() && response && currentFingerprint !== String(state.baseline || '')) {
      if (await finishExisting(operationId, response)) {
        clearRecoveryState();
        return true;
      }
    }

    const startedMs = Number(state.started_ms || Date.now());
    beginProgressTracking(operationId, state);
    sampleProgress(state);
    const config = recoveryProgressConfig();
    if (!config || !RECOVERY_PROGRESS?.decideRecovery) return false;
    const decision = RECOVERY_PROGRESS.decideRecovery({
      nowMs: Date.now(),
      startedMs: Number.isFinite(startedMs) ? startedMs : Date.now(),
      lastProgressMs: progressTracker?.lastProgressMs ?? startedMs,
      generating: generating(),
      connectionError: connectionFailure(),
      securityChallenge: securityChallenge(),
      reloadCount: Number(state.reload_count || 0)
    }, config);

    if (decision.recover) {
      const recoveryStartedAtMs = Date.now();
      const next = {
        ...state,
        recovery_context: state.recovery_context || recoveryContextFromActiveState(),
        reload_count: Number(state.reload_count || 0) + 1,
        phase: 'reloaded',
        reload_at: new Date().toISOString(),
        recovery_reason: decision.reason,
        recovery_started_at_ms: recoveryStartedAtMs,
        recovery_last_progress_ms: progressTracker?.lastProgressMs ?? startedMs
      };
      writeRecoveryState(next);
      await report('chatgpt_recovery', {
        phase: 'reloading',
        operation_id: operationId,
        recovery_action: 'reload_page',
        reload_count: next.reload_count,
        recovery_reason: decision.reason,
        age_ms: decision.ageMs,
        idle_ms: decision.idleMs,
        recovery_started_at_ms: recoveryStartedAtMs,
        generation_timeout_ms: GENERATION_TIMEOUT_MS,
        recovery_trigger_ms: RECOVERY_TRIGGER_MS,
        hard_ceiling_ms: RECOVERY_HARD_CEILING_MS
      });
      progressOperationId = null;
      progressTracker = null;
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
      if (await finishVisibleResponse(operationId, current, state.baseline)) {
        clearRecoveryState();
        return;
      }
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
    if (!generating() && response && currentFingerprint !== String(state.baseline || '')) {
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
      await report('chatgpt_recovery', {
        phase: 'preserve_current_chat',
        operation_id: operationId,
        recovery_action: 'preserve_current_chat',
        reason: 'no_verified_usage_or_context_exhaustion',
        ...recoveryCompletionFields(state, 'resumed')
      });
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
      await report('chatgpt_recovery', {
        phase: 'ready_for_retry',
        operation_id: operationId,
        recovery_action: 'fresh_chat_prepared',
        replacement_reason: reason,
        ...recoveryCompletionFields(state, 'resumed')
      });
    } catch (error) {
      await markRetryableFailure(operationId, `CHAT_RECOVERY_FAILED: ${String(error?.message || error)}`);
      await report('chatgpt_recovery', {
        phase: 'failed',
        operation_id: operationId,
        recovery_action: 'retry_runner',
        error: String(error?.message || error),
        ...recoveryCompletionFields(state, 'failed')
      });
    }
    if (readRecoveryState()?.resume_operation_id === operationId) return;
    clearRecoveryState();
  }

  async function inspect() {
    let state = readRecoveryState();
    if (state?.operation_id) {
      if (state.phase === 'context_exhausted') {
        await handleContextExhausted(state);
        return;
      }

      const current = await operation(state.operation_id);
      if (!current) {
        const missingSince = Number(state.missing_operation_since_ms || Date.now());
        const now = Date.now();
        const age = now - missingSince;
        const lastReported = Number(state.missing_operation_last_report_ms || 0);
        if (age >= MISSING_OPERATION_GRACE_MS) {
          await report('chatgpt_recovery', {
            phase: 'operation_missing_expired',
            operation_id: state.operation_id,
            recovery_action: 'clear_stale_state',
            missing_operation_age_ms: age,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
          clearInterruptedState();
          return;
        }
        const nextState = { ...state };
        if (!state.missing_operation_since_ms) nextState.missing_operation_since_ms = missingSince;
        if (!lastReported || now - lastReported >= MISSING_OPERATION_REPORT_MS) {
          nextState.missing_operation_last_report_ms = now;
          writeRecoveryState(nextState);
          await report('chatgpt_recovery', {
            phase: 'operation_lookup_unavailable',
            operation_id: state.operation_id,
            recovery_action: 'wait_for_operation_state',
            missing_operation_age_ms: age,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
        } else if (!state.missing_operation_since_ms) {
          writeRecoveryState(nextState);
        }
        return;
      }
      if (state.missing_operation_since_ms || state.missing_operation_last_report_ms) {
        const recoveredState = { ...state };
        delete recoveredState.missing_operation_since_ms;
        delete recoveredState.missing_operation_last_report_ms;
        writeRecoveryState(recoveredState);
        state = recoveredState;
      }
      if (current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') {
        if (await finishVisibleResponse(state.operation_id, current, state.baseline)) {
          clearInterruptedState();
          return;
        }
        clearInterruptedState();
        return;
      }

      if (state.phase === 'retry_ready') {
        if (state.resume_operation_id !== state.operation_id) {
          await report('chatgpt_recovery', {
            phase: 'retry_resume_marker_invalid',
            operation_id: state.operation_id,
            recovery_action: 'retry_runner',
            observed_status: current.status
          });
          return;
        }
        if (current.status === 'queued') {
          await report('chatgpt_recovery', {
            phase: 'retry_waiting',
            operation_id: state.operation_id,
            recovery_action: 'wait_for_runner_resume'
          });
          return;
        }
        if (['claimed', 'generating', 'running'].includes(current.status)) {
          clearRecoveryState();
          await report('chatgpt_recovery', {
            phase: 'retry_resumed',
            operation_id: state.operation_id,
            recovery_action: 'monitor_resumed_operation',
            observed_status: current.status
          });
          return;
        }
        await report('chatgpt_recovery', {
          phase: 'retry_resume_state_unexpected',
          operation_id: state.operation_id,
          recovery_action: 'retry_runner',
          observed_status: current.status
        });
        return;
      }

      if (state.phase === 'monitoring') {
        beginProgressTracking(state.operation_id, state);
        sampleProgress(state);
        await preserveOrReload(state.operation_id, state);
        return;
      }

      await handleReloadRecovery(state);
      return;
    }

    const operationId = activeOperationId();
    if (!operationId) return;
    const current = await operation(operationId);
    if (!current) {
      await report('chatgpt_recovery', {
        phase: 'operation_lookup_unavailable',
        operation_id: operationId,
        recovery_action: 'wait_for_operation_state',
        grace_ms: MISSING_OPERATION_GRACE_MS
      });
      return;
    }
    if (current.status === 'completed' || current.status === 'failed' || current.status === 'cancelled') {
      if (await finishVisibleResponse(operationId, current, '')) {
        clearInterruptedState();
      } else if (current.status !== 'completed') {
        clearInterruptedState();
      }
      return;
    }

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
      chat_url: location.href,
      reload_count: 0,
      phase: 'monitoring',
      chat_url: typeof current.chat_url === 'string' ? current.chat_url : location.href,
      recovery_context: recoveryContextFromActiveState()
    };
    writeRecoveryState(stateForTimer);

    beginProgressTracking(operationId, stateForTimer);
    sampleProgress(stateForTimer);
    if (contextExhausted()) return;
    await preserveOrReload(operationId, stateForTimer);
  }

  async function runInspection() {
    if (inspecting) return;
    inspecting = true;
    try {
      await inspect();
    } finally {
      inspecting = false;
    }
  }

  async function start() {
    await report('chatgpt_recovery', {
      phase: 'started',
      recovery_action: 'monitor',
      generation_timeout_ms: GENERATION_TIMEOUT_MS,
      recovery_grace_ms: RECOVERY_GRACE_MS,
      recovery_stall_ms: RECOVERY_STALL_MS,
      recovery_hard_ceiling_ms: RECOVERY_HARD_CEILING_MS
    });
    if (RECOVERY_PROGRESS?.attachProgressObserver && document.documentElement) {
      const config = recoveryProgressConfig();
      if (config) {
        progressObserverHandle = RECOVERY_PROGRESS.attachProgressObserver({
          root: document.documentElement,
          readSample: assistantProgressSample,
          onSample: (sample, nowMs) => {
            if (!progressOperationId || !progressTracker || !sample) return;
            progressTracker.observe(sample, nowMs);
            const state = readRecoveryState();
            if (state?.operation_id === progressOperationId && state.phase === 'monitoring') {
              persistProgressState(state);
            }
          },
          config
        });
      }
    }
    setInterval(() => { runInspection().catch(() => {}); }, POLL_MS);
    await runInspection();
  }

  start().catch(() => {});
})();
