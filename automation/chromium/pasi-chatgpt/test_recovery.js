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
  assert.match(source, /if \(!current \|\| current\.status === 'completed' \|\| current\.status === 'failed' \|\| current\.status === 'cancelled'\) return/);
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
