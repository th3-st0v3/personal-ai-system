const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

test('bridge extension is Manifest V3 and has no page DOM integration', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.background.service_worker, 'background.js');
  assert.equal(manifest.permissions?.length ?? 0, 0);
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1:8765/*']);
  assert.equal(manifest.content_scripts, undefined);
  assert.equal(manifest.side_panel, undefined);
  assert.equal(manifest.web_accessible_resources, undefined);
});

test('bridge worker contains no browser-page DOM or tab injection APIs', () => {
  assert.doesNotMatch(background, /document\b|window\b|querySelector|innerText|textContent|MutationObserver|localStorage/);
  assert.doesNotMatch(background, /chrome\.tabs|chrome\.scripting|chrome\.sidePanel/);
});

test('bridge worker caches its token and refreshes once after unauthorized responses', () => {
  assert.match(background, /let cachedBridgeToken = null/);
  assert.match(background, /let bridgeTokenPromise = null/);
  assert.match(background, /if \(!forceRefresh && cachedBridgeToken\) return cachedBridgeToken/);
  assert.match(background, /if \(response\.status === 401\)/);
  assert.match(background, /cachedBridgeToken = null/);
  assert.match(background, /token = await bridgeToken\(true\)/);
});

test('bridge worker enforces bounded request timeouts and an allowlist', () => {
  assert.match(background, /const BRIDGE_ROUTES = new Set/);
  assert.match(background, /const BRIDGE_OPERATION_RE/);
  assert.match(background, /Math\.min\(Math\.max\(requestedTimeout, 250\), 10000\)/);
  assert.match(background, /allowedBridgeRequest\(method, path\)/);
});
