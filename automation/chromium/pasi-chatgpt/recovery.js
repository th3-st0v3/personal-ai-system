(() => {
  'use strict';

  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const RECOVERY_OPERATION_KEY = 'recovery_operation_id';
  const TIMEOUT_POLICY = globalThis.PASI_TIMEOUT_POLICY?.get?.() || globalThis.PASI_TIMEOUT_POLICY?.defaults || {};
  const POLL_MS = TIMEOUT_POLICY.pollMs || 2000;
  const GENERATION_TIMEOUT_MS = TIMEOUT_POLICY.generationMs || 1500 * 1000;
  const RECOVERY_TRIGGER_MS = TIMEOUT_POLICY.recoveryTriggerMs || GENERATION_TIMEOUT_MS;
  const RECOVERY_GRACE_MS = TIMEOUT_POLICY.recoveryGraceMs || 600 * 1000;
  const MAX_RELOADS = 1;
  const MAX_NEW_CHAT_WAIT_MS = 30 * 1000;
  const MAX_CONTEXT_RECOVERIES = 1;
  const MISSING_OPERATION_GRACE_MS = 60 * 1000;
  const MISSING_OPERATION_REPORT_MS = 10 * 1000;
  const RECOVERY_VERSION = '1.0.6';
  let inspecting = false;

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const preserveLineBreaks = (value) => String(value || '')
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t]+(?=\n)/g, '')
    .trim();
  const collapseWhitespace = (value) => String(value || '').replace(/\s+/g, ' ').trim();
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

  function detectorState() {
    return globalThis.PASIChatGPTDetectors?.detect?.() || {
      context_exhausted: false,
      usage_limited: false,
      auth_required: false,
      connection_failure: false
    };
  }

  function securityChallenge() {
    return detectorState().auth_required === true;
  }

  function connectionFailure() {
    return detectorState().connection_failure === true;
  }

  function contextExhausted() {
    return detectorState().context_exhausted === true;
  }

  function usageLimited() {
    const state = detectorState();
    return state.context_exhausted !== true && state.usage_limited === true;
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

  function fingerprint() {
    return collapseWhitespace(latestAssistant()).slice(-4000);
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

  async function observeExisting(operationId, responseText) {
    const bounded = String(responseText || '').slice(0, 50000);
    if (!bounded.trim()) return false;
    await report('chatgpt_response', {
      active_operation_id: operationId,
      response_text: bounded,
      response_text_available: true,
      chat_exhausted: contextExhausted(),
      recovery_action: 'observe_response_only'
    });
    return true;
  }

  function clearInterruptedState() {
    clearRecoveryState();
    localStorage.removeItem(ACTIVE_KEY);
  }

  async function finishVisibleResponse(operationId, current, baseline) {
    if (!current || current.operation_type !== 'prompt') return false;
    if (await finishPersistedResponse(current)) return true;
    const response = latestAssistant();
    const currentFingerprint = fingerprint();
    if (generating() || !response || currentFingerprint === String(baseline || '')) return false;
    return observeExisting(operationId, response);
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
      await report('chatgpt_recovery', { phase: 'retryable_failure_observed', operation_id: operationId, `CHAT_RECOVERY_FAILED: ${String(error?.message || error)}` });
      await report('chatgpt_recovery', { phase: 'failed', operation_id: operationId, recovery_action: 'retry_runner', error: String(error?.message || error) });
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
        const lastReported = Number(state.missing_operation_last_report_ms || 0);
        const nextState = { ...state };
        if (!state.missing_operation_since_ms) nextState.missing_operation_since_ms = missingSince;
        if (!lastReported || now - lastReported >= MISSING_OPERATION_REPORT_MS) {
          nextState.missing_operation_last_report_ms = now;
          writeRecoveryState(nextState);
          await report('chatgpt_recovery', {
            phase: 'operation_lookup_unavailable',
            operation_id: state.operation_id,
            recovery_action: 'wait_for_operation_state',
            missing_operation_age_ms: now - missingSince,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
        } else if (!state.missing_operation_since_ms) {
          writeRecoveryState(nextState);
        }
        if (now - missingSince >= MISSING_OPERATION_GRACE_MS) {
          await report('chatgpt_recovery', {
            phase: 'operation_missing_expired',
            operation_id: state.operation_id,
            recovery_action: 'clear_stale_recovery_state',
            missing_operation_age_ms: now - missingSince,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
          clearRecoveryState();
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
      reload_count: 0,
      phase: 'monitoring',
      chat_url: typeof current.chat_url === 'string' ? current.chat_url : location.href,
      recovery_context: recoveryContextFromActiveState()
    };
    writeRecoveryState(stateForTimer);

    const age = Date.now() - startedMs;
    if (age < RECOVERY_TRIGGER_MS && !connectionFailure() && !contextExhausted()) return;
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
    await globalThis.PASI_TIMEOUT_POLICY?.load?.();
    await report('chatgpt_recovery', { phase: 'started', recovery_action: 'monitor', generation_timeout_ms: GENERATION_TIMEOUT_MS, recovery_grace_ms: RECOVERY_GRACE_MS });
    setInterval(() => { runInspection().catch(() => {}); }, POLL_MS);
    await runInspection();
  }

  start().catch(() => {});
})();
