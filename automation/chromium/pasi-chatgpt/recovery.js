(() => {
  'use strict';

  const RECOVERY_VERSION = '1.0.6';
  const TIMEOUT_POLICY = globalThis.PASI_TIMEOUT_POLICY?.get?.() || globalThis.PASI_TIMEOUT_POLICY?.defaults || {};
  const POLL_MS = TIMEOUT_POLICY.pollMs || 2000;
  const MISSING_OPERATION_GRACE_MS = 60 * 1000;
  const MISSING_OPERATION_REPORT_MS = 10 * 1000;
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const ACTIVE_KEY = 'pasi:active-operation';
  let inspecting = false;

  function normalize(value) {
    return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function collapseWhitespace(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function detectorState() {
    return globalThis.PASIChatGPTDetectors?.detect?.() || {
      context_exhausted: false,
      usage_limited: false,
      auth_required: false,
      connection_failure: false
    };
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

  function securityChallenge() {
    return detectorState().auth_required === true;
  }

  function chatUrl() {
    return /^https:\/\/chatgpt\.com(?::\d+)?\/c\//.test(location.href) ? location.href : null;
  }

  function latestAssistant() {
    const nodes = document.querySelectorAll('[data-message-author-role="assistant"] .markdown, [data-message-author-role="assistant"]');
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const text = String(nodes[index].innerText || nodes[index].textContent || '')
        .replace(/\r\n?/g, '\n')
        .replace(/[ \t]+(?=\n)/g, '')
        .trim();
      if (text) return text.slice(0, 50000);
    }
    return '';
  }

  function readRecoveryState() {
    try {
      const value = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch (_) {
      return null;
    }
  }

  function readActiveOperationId() {
    try {
      const value = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      return typeof value?.operation_id === 'string' && value.operation_id.trim()
        ? value.operation_id
        : null;
    } catch (_) {
      return null;
    }
  }

  async function bridge(path, options = {}) {
    return new Promise((resolve, reject) => {
      if (!globalThis.chrome?.runtime?.sendMessage) {
        reject(new Error('PASI_NATIVE: extension messaging API unavailable'));
        return;
      }
      const timeoutMs = Number(options.timeout || 10000);
      const timer = setTimeout(() => reject(new Error('PASI_NATIVE: recovery bridge request timed out')), timeoutMs);
      try {
        chrome.runtime.sendMessage({
          type: 'pasi-bridge-request',
          path: String(path || ''),
          method: String(options.method || 'GET').toUpperCase(),
          body: options.body ?? null
        }, (response) => {
          clearTimeout(timer);
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError) {
            reject(new Error(String(runtimeError.message || runtimeError)));
            return;
          }
          if (!response || typeof response !== 'object') {
            reject(new Error('PASI_NATIVE: invalid recovery bridge response'));
            return;
          }
          const text = typeof response.text === 'string' ? response.text : '';
          resolve({
            ok: response.ok === true,
            status: Number(response.status || 0),
            json: () => JSON.parse(text)
          });
        });
      } catch (error) {
        clearTimeout(timer);
        reject(error);
      }
    });
  }

  async function operation(operationId) {
    try {
      const response = await bridge('/operation?operation_id=' + encodeURIComponent(operationId));
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
        body: {
          observation: {
            schema_version: 'pasi-chatgpt-recovery-v3',
            captured_at: new Date().toISOString(),
            data: {
              kind,
              recovery_version: RECOVERY_VERSION,
              chat_url: chatUrl(),
              ...data
            }
          }
        }
      });
    } catch (_) {}
  }

  async function inspect() {
    if (inspecting) return;
    inspecting = true;
    try {
      const state = readRecoveryState();
      const activeOperationId =
        state?.operation_id ||
        state?.recovery_operation_id ||
        state?.resume_operation_id ||
        readActiveOperationId();
      if (!activeOperationId) return;

      const current = await operation(String(activeOperationId));
      if (!current) {
        const now = Date.now();
        const existingMissingSince = Number(state?.missing_operation_since_ms || 0);
        const missingSince = Number.isFinite(existingMissingSince) && existingMissingSince > 0
          ? existingMissingSince
          : now;
        const lastReported = Number(state?.missing_operation_last_report_ms || 0);
        if (!Number.isFinite(existingMissingSince) || existingMissingSince <= 0) {
          try {
            const next = {
              ...(state || {}),
              operation_id: String(activeOperationId),
              missing_operation_since_ms: missingSince,
              missing_operation_last_report_ms: 0
            };
            localStorage.setItem(RECOVERY_KEY, JSON.stringify(next));
          } catch (_) {}
        }
        if (!lastReported || now - lastReported >= MISSING_OPERATION_REPORT_MS) {
          await report('chatgpt_recovery', {
            phase: 'operation_lookup_unavailable',
            operation_id: String(activeOperationId),
            recovery_action: 'observe_only',
            missing_operation_age_ms: now - missingSince,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
          try {
            const next = {
              ...(readRecoveryState() || state || {}),
              operation_id: String(activeOperationId),
              missing_operation_since_ms: missingSince,
              missing_operation_last_report_ms: now
            };
            localStorage.setItem(RECOVERY_KEY, JSON.stringify(next));
          } catch (_) {}
        }
        if (state && now - missingSince >= MISSING_OPERATION_GRACE_MS) {
          await report('chatgpt_recovery', {
            phase: 'operation_missing_expired',
            operation_id: String(activeOperationId),
            recovery_action: 'observe_only',
            missing_operation_age_ms: now - missingSince,
            grace_ms: MISSING_OPERATION_GRACE_MS
          });
        }
        return;
      }

      try {
        const persisted = readRecoveryState();
        if (persisted && (persisted.missing_operation_since_ms || persisted.missing_operation_last_report_ms)) {
          const next = { ...persisted };
          delete next.missing_operation_since_ms;
          delete next.missing_operation_last_report_ms;
          localStorage.setItem(RECOVERY_KEY, JSON.stringify(next));
        }
      } catch (_) {}

      const responseText = latestAssistant();
      const stateData = {
        operation_id: String(activeOperationId),
        operation_status: String(current.status || ''),
        operation_type: String(current.operation_type || ''),
        response_available: Boolean(responseText),
        connection_failure: connectionFailure(),
        context_exhausted: contextExhausted(),
        usage_limited: usageLimited(),
        security_challenge: securityChallenge(),
        recovery_phase: state?.phase || 'untracked',
        recovery_action: 'observe_only'
      };

      if (responseText) {
        await report('chatgpt_response', {
          active_operation_id: String(activeOperationId),
          response_text: responseText,
          response_text_available: true,
          recovery_action: 'observe_response_only'
        });
      }

      await report('chatgpt_recovery', stateData);
    } finally {
      inspecting = false;
    }
  }

  async function start() {
    await globalThis.PASI_TIMEOUT_POLICY?.load?.();
    await report('chatgpt_recovery', {
      phase: 'started',
      recovery_action: 'observe_only',
      recovery_version: RECOVERY_VERSION
    });
    setInterval(() => {
      inspect().catch(() => {});
    }, POLL_MS);
    await inspect();
  }

  start().catch(() => {});
})();
