const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('automation/chromium/pasi-chatgpt/recovery.js', 'utf8');

test('recovery uses the requested 25-minute generation ceiling and starts recovery at the ceiling', () => {
  assert.match(source, /GENERATION_TIMEOUT_MS = 25 \* 60 \* 1000/);
  assert.match(source, /RECOVERY_TRIGGER_MS = GENERATION_TIMEOUT_MS/);
  assert.match(source, /RECOVERY_GRACE_MS = 10 \* 60 \* 1000/);
  assert.match(source, /generation_timeout_ms: GENERATION_TIMEOUT_MS/);
});

test('recovery preserves a verified response and includes response text in completion persistence', () => {
  assert.match(source, /preserve_response/);
  assert.match(source, /response_text: bounded/);
  assert.match(source, /response_text_available: Boolean\(bounded\)/);
  assert.match(source, /location\.reload\(\)/);
  assert.match(source, /queueNewChat/);
  assert.match(source, /operation_type: 'new_chat'/);
  assert.match(source, /RECOVERY_OPERATION_KEY = 'recovery_operation_id'/);
  assert.match(source, /recoveryState, \[RECOVERY_OPERATION_KEY\]/);
  assert.match(source, /CHAT_RECOVERED_RETRY/);
  assert.match(source, /grace_wait/);
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
  assert.match(source, /knownChatUrl \|\| location\.href/);
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
  assert.match(source, /response_text_available: Boolean\(bounded\.trim\(\)\)/);
});
