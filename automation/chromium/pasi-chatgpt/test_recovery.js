const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('automation/chromium/pasi-chatgpt/recovery.js', 'utf8');
const detectors = fs.readFileSync('automation/chromium/pasi-chatgpt/detectors.js', 'utf8');
const progress = require('./recovery_progress.js');

test('recovery uses progress-based stall detection with a hard ceiling instead of age-only reloads', () => {
  assert.match(source, /const GENERATION_TIMEOUT_MS = TIMEOUT_POLICY\.generationMs \|\| 60 \* 60 \* 1000/);
  assert.match(source, /const RECOVERY_STALL_MS = TIMEOUT_POLICY\.recoveryStallMs \|\| 8 \* 60 \* 1000/);
  assert.match(source, /const RECOVERY_HARD_CEILING_MS = TIMEOUT_POLICY\.recoveryHardCeilingMs \|\| 90 \* 60 \* 1000/);
  assert.match(source, /RECOVERY_PROGRESS.*decideRecovery/);
  assert.match(source, /lastProgressMs/);
  assert.match(source, /recovery_stall_ms: RECOVERY_STALL_MS/);
  assert.match(source, /hard_ceiling_ms: RECOVERY_HARD_CEILING_MS/);
  assert.doesNotMatch(source, /Date\.now\(\) - startedMs < RECOVERY_TRIGGER_MS/);
  assert.doesNotMatch(source, /age < RECOVERY_TRIGGER_MS/);
});

test('recovery preserves a verified response and includes response text in completion persistence', () => {
  assert.match(source, /preserve_response/);
  assert.match(source, /response_text: bounded/);
  assert.match(source, /response_text_available: true/);
  assert.match(source, /location\.reload\(\)/);
  assert.match(source, /queueNewChat/);
  assert.match(source, /operation_type: 'new_chat'/);
  assert.match(source, /RECOVERY_OPERATION_KEY = 'recovery_operation_id'/);
  assert.match(source, /\[RECOVERY_OPERATION_KEY\]: newOperationId/);
  assert.match(source, /CHAT_RECOVERED_RETRY/);
  assert.match(source, /grace_wait/);
});

test('recovery observations identify the active prompt operation so the bridge can persist response evidence', () => {
  assert.match(source, /active_operation_id: operationId/);
  assert.match(source, /schema_version: 'pasi-chatgpt-recovery-v3'/);
});

test('recovery never prepares a replacement chat without verified exhaustion', () => {
  assert.match(source, /function replacementReason\(\)/);
  assert.match(source, /const reason = replacementReason\(\)/);
  assert.match(source, /if \(!reason\)/);
  assert.match(source, /preserve_current_chat/);
  assert.match(source, /no_verified_usage_or_context_exhaustion/);
});

test('recovery clears terminal operations and does not loop on the same failed operation', () => {
  assert.match(source, /current\.status === 'completed' \|\| current\.status === 'failed' \|\| current\.status === 'cancelled'/);
  assert.match(source, /if \(!current\) return/);
});






async function runRecoveryScenario({ connectionError = false, lastProgressAgeMs = 100 }) {
  const vm = require('node:vm');
  const storage = new Map();
  const reports = [];
  let reloads = 0;
  const now = Date.now();
  storage.set('pasi:chatgpt-recovery', JSON.stringify({
    operation_id: 'op-scenario',
    started_ms: now - 1000,
    last_progress_ms: now - lastProgressAgeMs,
    baseline: '',
    chat_url: 'https://chatgpt.com/c/scenario',
    reload_count: 0,
    phase: 'monitoring'
  }));
  storage.set('pasi:active-operation', JSON.stringify({
    operation_id: 'op-scenario',
    operation_type: 'prompt'
  }));

  const stopButton = {
    getClientRects: () => [{ width: 1, height: 1 }],
    querySelectorAll: () => []
  };
  const connectionAlert = {
    innerText: connectionError ? 'Connection lost. Reconnecting…' : '',
    textContent: connectionError ? 'Connection lost. Reconnecting…' : '',
    getClientRects: () => [{ width: 1, height: 1 }],
    querySelectorAll: () => []
  };

  const document = {
    body: { innerText: '' },
    documentElement: {},
    querySelector(selector) {
      return selector.includes('stop-button') || selector.includes('Stop generating') ? stopButton : null;
    },
    querySelectorAll(selector) {
      if (connectionError && selector === '[role="alert"]') return [connectionAlert];
      return [];
    }
  };

  const bridgeRequests = [];
  const chrome = {
    runtime: {
      lastError: null,
      sendMessage(message, callback) {
        bridgeRequests.push(message);
        if (String(message.path || '').startsWith('/operation?operation_id=')) {
          callback({
            ok: true,
            status: 200,
            text: JSON.stringify({
              operation: {
                operation_id: 'op-scenario',
                operation_type: 'prompt',
                status: 'running',
                response_text: '',
                response_text_available: false,
                created_at: new Date(now - 1000).toISOString(),
                updated_at: new Date(now - 1000).toISOString()
              }
            })
          });
          return;
        }
        if (message.path === '/browser/observation') {
          try {
            const body = typeof message.body === 'object' ? message.body : {};
            reports.push(body.observation?.data || {});
          } catch (_) {}
          callback({ ok: true, status: 200, text: '{}' });
          return;
        }
        callback({ ok: true, status: 200, text: '{}' });
      }
    }
  };

  class FakeMutationObserver {
    constructor() {}
    observe() {}
    disconnect() {}
  }

  const context = {
    console,
    Date,
    JSON,
    Map,
    Set,
    Promise,
    Object,
    Number,
    String,
    Boolean,
    Array,
    Math,
    Error,
    RegExp,
    parseInt,
    isFinite,
    document,
    chrome,
    location: {
      href: 'https://chatgpt.com/c/scenario',
      reload() { reloads += 1; }
    },
    localStorage: {
      getItem(key) { return storage.has(key) ? storage.get(key) : null; },
      setItem(key, value) { storage.set(key, String(value)); },
      removeItem(key) { storage.delete(key); }
    },
    getComputedStyle() {
      return { display: 'block', visibility: 'visible' };
    },
    MutationObserver: FakeMutationObserver,
    setInterval() { return 1; },
    clearInterval() {},
    setTimeout,
    clearTimeout
  };
  context.globalThis = context;
  context.window = context;

  vm.runInNewContext(fs.readFileSync('automation/chromium/pasi-chatgpt/recovery_progress.js', 'utf8'), context);
  context.PASI_TIMEOUT_POLICY = {
    get: () => ({
      pollMs: 5,
      generationMs: 1000,
      recoveryTriggerMs: 1000,
      recoveryGraceMs: 10,
      recoveryStallMs: 10,
      recoveryHardCeilingMs: 5000,
      recoveryProgressSampleMs: 1,
      recoveryProgressPollMs: 10
    })
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  const recovery = JSON.parse(storage.get('pasi:chatgpt-recovery') || 'null');
  return { reloads, recovery, reports, bridgeRequests };
}

test('timeout recovery reloads a genuinely stalled active operation', async () => {
  const result = await runRecoveryScenario({ lastProgressAgeMs: 100 });
  assert.equal(result.reloads, 1);
  assert.equal(result.recovery?.phase, 'reloaded');
  assert.equal(result.recovery?.recovery_reason, 'no_progress');
  assert.ok(result.reports.some((event) => event.phase === 'reloading' && event.recovery_reason === 'no_progress'));
});

test('connection-loss recovery reloads immediately without waiting for the stall timeout', async () => {
  const result = await runRecoveryScenario({ connectionError: true, lastProgressAgeMs: 1 });
  assert.equal(result.reloads, 1);
  assert.equal(result.recovery?.phase, 'reloaded');
  assert.equal(result.recovery?.recovery_reason, 'connection_error');
  assert.ok(result.reports.some((event) => event.phase === 'reloading' && event.recovery_reason === 'connection_error'));
});

test('timeout recovery decision triggers only after observable no-progress while generating', () => {
  const config = progress.resolveRecoveryConfig({
    stallMs: 100,
    hardCeilingMs: 1000,
    maxReloads: 1
  });
  const decision = progress.decideRecovery({
    nowMs: 250,
    startedMs: 0,
    lastProgressMs: 100,
    generating: true,
    connectionError: false,
    securityChallenge: false,
    reloadCount: 0
  }, config);
  assert.equal(decision.recover, true);
  assert.equal(decision.reason, 'no_progress');
  assert.equal(decision.idleMs, 150);
});

test('connection-loss recovery triggers immediately even with a fresh generation heartbeat', () => {
  const config = progress.resolveRecoveryConfig({
    stallMs: 1000,
    hardCeilingMs: 5000,
    maxReloads: 1
  });
  const decision = progress.decideRecovery({
    nowMs: 250,
    startedMs: 0,
    lastProgressMs: 240,
    generating: true,
    connectionError: true,
    securityChallenge: false,
    reloadCount: 0
  }, config);
  assert.equal(decision.recover, true);
  assert.equal(decision.reason, 'connection_error');
  assert.equal(decision.idleMs, 10);
});

test('timeout and connection recovery remain blocked by a security challenge', () => {
  const config = progress.resolveRecoveryConfig({
    stallMs: 100,
    hardCeilingMs: 1000,
    maxReloads: 1
  });
  const decision = progress.decideRecovery({
    nowMs: 250,
    startedMs: 0,
    lastProgressMs: 0,
    generating: true,
    connectionError: true,
    securityChallenge: true,
    reloadCount: 0
  }, config);
  assert.equal(decision.recover, false);
  assert.equal(decision.reason, 'human_boundary');
});

test('connection interruption is recognized by both native recovery layers', () => {
  assert.match(detectors, /'connection interrupted'/);
  assert.match(source, /'connection interrupted'/);
});

test('connection failure detection is scoped to visible error/alert elements', () => {
  assert.match(source, /\[role="alert"\]/);
  assert.match(source, /\[aria-live="assertive"\]/);
  assert.match(source, /\[data-testid\*="connection"/);
  assert.match(source, /if \(!visibleElement\(element\)\) continue/);
  assert.doesNotMatch(source, /const text = normalize\(document\.body\?\.innerText \|\| ''\);\n    return \['network error'/);
});

test('recovery detects security challenges without attempting to bypass them', () => {
  assert.match(source, /captcha/);
  assert.match(source, /cloudflare/);
  assert.match(source, /turnstile/);
  assert.match(source, /manual_intervention_required/);
  assert.doesNotMatch(source, /password/);
  assert.doesNotMatch(source, /cookie/);
});

test('recovery does not consume ordinary queue work directly', () => {
  assert.match(source, /\/operation\?operation_id/);
  assert.match(source, /\/queue/);
  assert.doesNotMatch(source, /\/next-operation/);
});

test('recovery tracks monitoring state across reloads and handles context exhaustion separately', () => {
  assert.match(source, /function persistedResponse\(current\)/);
  assert.match(source, /finishPersistedResponse/);
  assert.match(source, /writeRecoveryState\(stateForTimer\)/);
  assert.match(source, /state\.phase === 'context_exhausted'/);
  assert.match(source, /async function handleContextExhausted\(state\)/);
  assert.match(source, /MAX_CONTEXT_RECOVERIES = 1/);
});

test('recovery never finalizes a partial assistant response during generation', () => {
  assert.match(source, /function generating\(\)/);
  const guardedFinalizers = source.match(/if \(!generating\(\) && response && currentFingerprint/g) || [];
  assert.equal(guardedFinalizers.length, 2);
});

test('recovery preserves response text casing while still normalizing marker checks', () => {
  assert.match(source, /const compact =/);
  assert.doesNotMatch(source, /const text = normalize\(markdown\[index\]/);
});

test('monitoring recovery invokes the progress decision core without an age gate', () => {
  assert.match(source, /if \(state\.phase === 'monitoring'\)/);
  assert.match(source, /beginProgressTracking\(state\.operation_id, state\)/);
  assert.match(source, /sampleProgress\(state\)/);
  assert.match(source, /await preserveOrReload\(state\.operation_id, state\)/);
  assert.doesNotMatch(source, /if \(Date\.now\(\) - startedMs < RECOVERY_TRIGGER_MS/);
});

test('monitoring recovery keeps the normal bounded reload path before reloaded-state handling', () => {
  assert.match(source, /if \(state\.phase === 'monitoring'\)/);
  assert.match(source, /await preserveOrReload\(state\.operation_id, state\)/);
  assert.match(source, /await handleReloadRecovery\(state\)/);
});

test('recovery refresh handling reads the current operation before using persisted response state', () => {
  assert.match(source, /const current = await operation\(operationId\)/);
  assert.match(source, /if \(!current\) return false/);
  assert.match(source, /finishPersistedResponse\(current\)/);
});

test('recovery carries bounded conversational context into the requeued operation', () => {
  assert.match(source, /function recoveryContextFromActiveState\(\)/);
  assert.match(source, /body\.recovery_context = recoveryContext/);
  assert.match(source, /state\.recovery_context \|\| recoveryContextFromActiveState\(\)/);
  assert.match(source, /CHAT_EXHAUSTED: verified conversation context exhaustion/);
});

test('recovery marks the original operation for exact resumption after preparing a fresh chat', () => {
  assert.match(source, /resume_operation_id: operationId/);
  assert.match(source, /phase: 'retry_ready'/);
  assert.match(source, /if \(readRecoveryState\(\)\?\.resume_operation_id === operationId\) return/);
});

test('reload recovery verifies the original operation is queued before leaving an exact resume marker', () => {
  assert.match(source, /const afterRetry = await operation\(operationId\)/);
  assert.match(source, /if \(!accepted \|\| afterRetry\?\.status !== 'queued'\)/);
  assert.match(source, /phase: 'retry_requeue_not_verified'/);
});

test('recovery does not discard persisted recovery state when the bridge temporarily cannot resolve an operation', () => {
  assert.match(source, /MISSING_OPERATION_GRACE_MS = 60 \* 1000/);
  assert.match(source, /phase: 'operation_lookup_unavailable'/);
  assert.match(source, /recovery_action: 'wait_for_operation_state'/);
  assert.match(source, /missing_operation_since_ms/);
  assert.match(source, /if \(!current\) \{/);
});

test('retry-ready recovery validates the resume marker before waiting for the queued operation', () => {
  assert.match(source, /if \(state\.phase === 'retry_ready'\)/);
  assert.match(source, /if \(state\.resume_operation_id !== state\.operation_id\)/);
  assert.match(source, /if \(current\.status === 'queued'\)/);
  assert.match(source, /phase: 'retry_waiting'/);
  assert.match(source, /recovery_action: 'wait_for_runner_resume'/);
  assert.match(source, /phase: 'retry_resume_marker_invalid'/);
});

test('retry-ready recovery clears only its recovery marker once the verified operation resumes running', () => {
  assert.match(source, /if \(state\.resume_operation_id !== state\.operation_id\)/);
  assert.match(source, /\['claimed', 'generating', 'running'\]\.includes\(current\.status\)/);
  assert.match(source, /clearRecoveryState\(\);/);
  assert.match(source, /phase: 'retry_resumed'/);
  assert.match(source, /recovery_action: 'monitor_resumed_operation'/);
  assert.match(source, /observed_status: current\.status/);
  assert.match(source, /phase: 'retry_resume_state_unexpected'/);
});

test('recovery clears transient missing-operation markers when the operation becomes resolvable again', () => {
  assert.match(source, /let state = readRecoveryState\(\)/);
  assert.match(source, /if \(state\.missing_operation_since_ms \|\| state\.missing_operation_last_report_ms\)/);
  assert.match(source, /delete recoveredState\.missing_operation_since_ms/);
  assert.match(source, /delete recoveredState\.missing_operation_last_report_ms/);
  assert.match(source, /state = recoveredState/);
});

test('recovery throttles repeated missing-operation reports without clearing persisted recovery state', () => {
  assert.match(source, /MISSING_OPERATION_REPORT_MS = 10 \* 1000/);
  assert.match(source, /missing_operation_last_report_ms/);
  assert.match(source, /now - lastReported >= MISSING_OPERATION_REPORT_MS/);
  assert.match(source, /operation_lookup_unavailable/);
  assert.match(source, /wait_for_operation_state/);
  assert.match(source, /if \(!current\) \{/);
});

test('recovery serializes inspection so a slow recovery cannot overlap and duplicate recovery work', () => {
  assert.match(source, /let inspecting = false/);
  assert.match(source, /async function runInspection\(\)/);
  assert.match(source, /if \(inspecting\) return/);
  assert.match(source, /inspecting = true/);
  assert.match(source, /finally \{/);
  assert.match(source, /inspecting = false/);
  assert.match(source, /setInterval\(\(\) => \{ runInspection\(\)\.catch\(\(\) => \{\}\); \}, POLL_MS\)/);
  assert.match(source, /await runInspection\(\)/);
});

test('response recovery persists observation before completion acknowledgement and requires nonblank evidence', () => {
  assert.match(source, /await report\('chatgpt_response'/);
  assert.match(source, /const available = Boolean\(bounded\.trim\(\)\)/);
  assert.match(source, /if \(!available\) return false/);
});

test('response recovery sends captured response text with completion acknowledgement', () => {
  assert.ok(source.includes("const bounded = String(responseText || '').slice(0, MAX_RESPONSE_TEXT_CHARS)"));
  assert.match(source, /if \(!available\) return false/);
  assert.match(source, /response_text: bounded/);
  assert.match(source, /response_text_available: true/);
});

test('response recovery retries a lost completion acknowledgement within a bounded budget', () => {
  assert.match(source, /for \(let attempt = 1; attempt <= 3; attempt \+= 1\)/);
  assert.match(source, /if \(finished\.ok\) return true/);
  assert.match(source, /const acknowledged = await operation\(operationId\)/);
  assert.match(source, /acknowledged\?\.status === 'completed'/);
  assert.match(source, /acknowledged\?\.response_text_available === true/);
  assert.match(source, /if \(attempt < 3\) await sleep\(Math\.min\(POLL_MS, 500\)\)/);
  assert.match(source, /phase: 'completion_ack_failed'/);
});


test('terminal recovery attempts a bound visible assistant response before clearing state', () => {
  assert.match(source, /async function finishVisibleResponse\(operationId, current, baseline\)/);
  assert.match(source, /if \(await finishVisibleResponse\(operationId, current, state\.baseline\)\)/);
  assert.match(source, /if \(generating\(\) \|\| !response \|\| currentFingerprint === String\(baseline \|\| ''\)\) return false/);
});


test('recovery expires vanished operations after the bounded missing-operation grace period', () => {
  assert.match(source, /MISSING_OPERATION_GRACE_MS = 60 \* 1000/);
  assert.match(source, /const age = now - missingSince/);
  assert.match(source, /if \(age >= MISSING_OPERATION_GRACE_MS\)/);
  assert.match(source, /phase: 'operation_missing_expired'/);
  assert.match(source, /recovery_action: 'clear_stale_state'/);
  assert.match(source, /clearInterruptedState\(\)/);
});
