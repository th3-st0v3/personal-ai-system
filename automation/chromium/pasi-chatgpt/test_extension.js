const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const content = fs.readFileSync(path.join(root, 'content.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

test('native extension is Manifest V3 with required host permissions', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.background.service_worker, 'background.js');
  assert.ok(manifest.permissions.includes('alarms'));
  assert.ok(manifest.permissions.includes('tabs'));
  assert.ok(manifest.host_permissions.includes('http://127.0.0.1:8765/*'));
});

test('native content controller uses standard fetch instead of GM APIs', () => {
  assert.match(content, /fetch\(BRIDGE/);
  assert.doesNotMatch(content, /GM_xmlhttpRequest|GM_getValue|GM_setValue/);
  assert.match(content, /new_chat/);
  assert.match(content, /select_reasoning/);
  assert.match(content, /attach_github/);
  assert.match(content, /operation\.operation_type/);
});

test('native controller reports health and preserves interrupted-operation recovery', () => {
  assert.match(content, /chatgpt_health/);
  assert.match(content, /localStorage/);
  assert.match(content, /browser page reloaded during operation/);
  assert.match(content, /CHAT_EXHAUSTED/);
});

test('background service worker performs bounded stale-tab recovery', () => {
  assert.match(background, /chrome\.alarms\.create/);
  assert.match(background, /chrome\.tabs\.query/);
  assert.match(background, /chrome\.tabs\.reload/);
  assert.match(background, /MAX_REFRESHES/);
  assert.match(background, /auth_required/);
});
