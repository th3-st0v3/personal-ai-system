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
  assert.match(source, /CHAT_RECOVERED_RETRY/);
  assert.match(source, /grace_wait/);
});

test('recovery never prepares a replacement chat without verified exhaustion', () => {
  assert.match(source, /function providerUsageExhausted\(\)/);
  assert.match(source, /function replacementAllowed\(\)/);
  assert.match(source, /if \(!replacementAllowed\(\)\)/);
  assert.match(source, /CHAT_RECOVERY_WAITING/);
  assert.match(source, /retry_runner_without_new_chat/);
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
