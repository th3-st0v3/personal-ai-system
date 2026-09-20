const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('automation/chromium/pasi-chatgpt/recovery.js', 'utf8');

test('recovery companion uses the shared timeout policy and bounded observation loop', () => {
  assert.match(source, /PASI_TIMEOUT_POLICY/);
  assert.match(source, /const POLL_MS/);
  assert.ok(source.includes('const MISSING_OPERATION_GRACE_MS = 60 * 1000;'));
  assert.ok(source.includes('const MISSING_OPERATION_REPORT_MS = 10 * 1000;'));
  assert.match(source, /setInterval\(\(\) =>/);
});

test('recovery companion is strictly observe-only', () => {
  assert.match(source, /recovery_action: 'observe_only'/);
  assert.match(source, /recovery_action: 'observe_response_only'/);
  assert.doesNotMatch(source, /location\.reload\(\)/);
  assert.doesNotMatch(source, /\/chat\/finished/);
  assert.doesNotMatch(source, /\/chat\/failed/);
  assert.doesNotMatch(source, /\/queue/);
  assert.doesNotMatch(source, /\/next-operation/);
  assert.doesNotMatch(source, /async function queueNewChat/);
  assert.doesNotMatch(source, /async function finishExisting/);
  assert.doesNotMatch(source, /async function markRetryableFailure/);
});

test('recovery companion preserves raw multiline response evidence', () => {
  assert.match(source, /replace\(\/\\r\\n\?\/g, '\\n'\)/);
  assert.ok(source.includes(".replace(/[ \\t]+(?=\\n)/g, '')"));
  assert.match(source, /response_text: responseText/);
});

test('recovery companion scopes detectors through the shared detector module', () => {
  assert.match(source, /PASIChatGPTDetectors\?\.detect/);
  assert.doesNotMatch(source, /document\.body\?\.innerText/);
});

test('recovery is observe-only and does not publish response evidence', () => {
  assert.match(source, /active_operation_id: String\(activeOperationId\)/);
  assert.match(source, /report\('chatgpt_recovery'/);
  assert.match(source, /observe_only/);
  assert.doesNotMatch(source, /report\('chatgpt_response'/);
  assert.doesNotMatch(source, /response_text: responseText/);
});

test('recovery persists missing-operation timestamps and supports all operation-id aliases', () => {
  assert.match(source, /state\?\.operation_id/);
  assert.match(source, /state\?\.recovery_operation_id/);
  assert.match(source, /state\?\.resume_operation_id/);
  assert.match(source, /missing_operation_since_ms/);
  assert.match(source, /localStorage\.setItem\(RECOVERY_KEY, JSON\.stringify\(next\)\)/);
});

test('recovery reports vanished operations and retains bounded grace semantics', () => {
  assert.match(source, /operation_lookup_unavailable/);
  assert.match(source, /operation_missing_expired/);
  assert.match(source, /missing_operation_age_ms/);
  assert.match(source, /grace_ms: MISSING_OPERATION_GRACE_MS/);
});

test('recovery serializes inspections so slow diagnostics cannot overlap', () => {
  assert.match(source, /let inspecting = false/);
  assert.match(source, /if \(inspecting\) return/);
  assert.match(source, /inspecting = true/);
  assert.match(source, /inspecting = false/);
});

test('recovery does not store secrets or credential material', () => {
  assert.doesNotMatch(source, /password/i);
  assert.doesNotMatch(source, /cookie/i);
  assert.doesNotMatch(source, /session token/i);
});
