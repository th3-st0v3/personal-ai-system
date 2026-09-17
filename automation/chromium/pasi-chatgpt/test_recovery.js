const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('automation/chromium/pasi-chatgpt/recovery.js', 'utf8');

test('recovery uses the requested 25-minute generation ceiling with a pre-timeout trigger', () => {
  assert.match(source, /GENERATION_TIMEOUT_MS = 25 \* 60 \* 1000/);
  assert.match(source, /RECOVERY_TRIGGER_MS = 24 \* 60 \* 1000/);
  assert.match(source, /RECOVERY_GRACE_MS = 10 \* 60 \* 1000/);
});

test('recovery can preserve a response, reload once, and prepare a fresh chat for retry', () => {
  assert.match(source, /preserve_response/);
  assert.match(source, /location\.reload\(\)/);
  assert.match(source, /queueNewChat/);
  assert.match(source, /operation_type: 'new_chat'/);
  assert.match(source, /CHAT_RECOVERED_RETRY/);
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
