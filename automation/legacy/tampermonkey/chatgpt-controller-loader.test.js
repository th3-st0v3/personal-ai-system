const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync(
  'automation/legacy/tampermonkey/chatgpt-controller-loader.user.js',
  'utf8',
);

test('legacy loader is explicitly deprecated and migration-only', () => {
  assert.match(source, /Deprecated/);
  assert.match(source, /migration-only/);
  assert.match(source, /native Chromium extension/);
  assert.doesNotMatch(source, /127\.0\.0\.1:8766/);
  assert.doesNotMatch(source, /controller\/manifest/);
  assert.doesNotMatch(source, /controller\/source/);
  assert.doesNotMatch(source, /recovery\/source/);
  assert.doesNotMatch(source, /GM_xmlhttpRequest/);
  assert.doesNotMatch(source, /\beval\s*\(/);
});

test('legacy loader no longer exposes a controller runtime entry point', () => {
  assert.doesNotMatch(source, /poll|verifyPublishedRelease|requestBytes|gitBlobSha1Bytes/);
  assert.match(source, /console\.warn/);
});
