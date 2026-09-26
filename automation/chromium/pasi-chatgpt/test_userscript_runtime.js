const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const runtimeSource = fs.readFileSync(path.join(root, 'userscript-runtime.js'), 'utf8');
const bridgeSource = fs.readFileSync(path.join(root, 'userscript-bridge.js'), 'utf8');
const backgroundSource = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

function loadUtils() {
  const context = vm.createContext({
    chrome: {},
    crypto: {randomUUID: () => 'test-id'},
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    console,
  });
  vm.runInContext(runtimeSource, context, {filename:'userscript-runtime.js'});
  return context.PASI_USERSCRIPT_RUNTIME_UTILS;
}

test('native userscript manifest enables MV3 userScripts with optional least-privilege grants', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.minimum_chrome_version, '135');
  assert.ok(manifest.permissions.includes('userScripts'));
  assert.ok(manifest.permissions.includes('storage'));
  assert.ok(Array.isArray(manifest.optional_permissions));
  assert.ok(manifest.optional_permissions.includes('contextMenus'));
  assert.ok(manifest.optional_host_permissions.includes('*://*/*'));
});

test('service worker loads the userscript runtime before controller logic', () => {
  assert.match(backgroundSource, /importScripts\('userscript-runtime\.js'\)/);
});

test('metadata parser extracts matches, grants, connect rules, and unsafe-world intent', () => {
  const {parseMetadata} = loadUtils();
  const metadata = parseMetadata([
    '// ==UserScript==',
    '// @name        Example',
    '// @namespace   tests',
    '// @version     1.2.3',
    '// @match       https://example.com/*',
    '// @connect     api.example.com',
    '// @grant       GM_getValue',
    '// @grant       GM_fetch',
    '// @grant       unsafeWindow',
    '// @run-at      document_start',
    '// @world       MAIN',
    '// ==/UserScript==',
    'console.log("ok");'
  ].join('\n'));
  assert.equal(metadata.name, 'Example');
  assert.deepEqual(metadata.matches, ['https://example.com/*']);
  assert.deepEqual(metadata.connects, ['api.example.com']);
  assert.ok(metadata.grants.includes('GM_getValue'));
  assert.ok(metadata.grants.includes('GM_fetch'));
  assert.ok(metadata.grants.includes('unsafeWindow'));
  assert.equal(metadata.runAt, 'document_start');
  assert.equal(metadata.world, 'MAIN');
});

test('metadata parser refuses scripts without a match pattern', () => {
  const {parseMetadata} = loadUtils();
  assert.throws(
    () => parseMetadata('// ==UserScript==\n// @name Bad\n// ==/UserScript==\n'),
    /at least one @match/
  );
});

test('connect enforcement accepts exact and wildcard hosts but rejects unrelated origins', () => {
  const {connectAllowed} = loadUtils();
  const script = {connects:['api.example.com', '*.trusted.test']};
  assert.equal(connectAllowed(script, 'https://api.example.com/v1'), true);
  assert.equal(connectAllowed(script, 'https://sub.trusted.test/v1'), true);
  assert.equal(connectAllowed(script, 'https://evil.example.com/v1'), false);
  assert.equal(connectAllowed(script, 'ftp://api.example.com/file'), false);
});

test('host-origin translation stays bounded to the requested match patterns', () => {
  const {matchOrigins} = loadUtils();
  assert.deepEqual(
    matchOrigins(['https://example.com/path/*', '*://*.trusted.test/*']),
    ['https://example.com/*', '*://*.trusted.test/*']
  );
  assert.deepEqual(matchOrigins(['<all_urls>']), ['*://*/*']);
});

test('storage GM APIs are present in the bootstrap but remain grant-gated', () => {
  const {createBootstrap, normalizeScript, parseMetadata} = loadUtils();
  const source = [
    '// ==UserScript==',
    '// @name Storage',
    '// @match https://example.com/*',
    '// @grant GM_getValue',
    '// ==/UserScript==',
    'GM_getValue("key");'
  ].join('\\n');
  const bootstrap = createBootstrap(normalizeScript(source, parseMetadata(source), null, false));
  assert.match(bootstrap, /assertGrant\("storage"\)/);
});

test('USER_SCRIPT bootstrap uses dedicated runtime messaging and recovery guards', () => {
  const {createBootstrap, normalizeScript, parseMetadata} = loadUtils();
  const source = [
    '// ==UserScript==',
    '// @name Worker',
    '// @match https://example.com/*',
    '// @grant GM_fetch',
    '// @grant GM_getValue',
    '// @connect api.example.com',
    '// ==/UserScript==',
    'GM_fetch("https://api.example.com");'
  ].join('\n');
  const script = normalizeScript(source, parseMetadata(source), null, false);
  const bootstrap = createBootstrap(script);
  assert.match(bootstrap, /chrome\.runtime\.sendMessage/);
  assert.match(bootstrap, /extension context invalidated/);
  assert.match(bootstrap, /GM_fetch/);
  assert.doesNotMatch(bootstrap, /pasi-userscript-main-response/);
});

test('MAIN bootstrap uses the isolated bridge and exposes unsafeWindow only on explicit grant', () => {
  const {createBootstrap, normalizeScript, parseMetadata} = loadUtils();
  const source = [
    '// ==UserScript==',
    '// @name Page',
    '// @match https://example.com/*',
    '// @grant unsafeWindow',
    '// @world MAIN',
    '// ==/UserScript==',
    'console.log(GM.unsafeWindow.location.href);'
  ].join('\n');
  const script = normalizeScript(source, parseMetadata(source), null, true);
  const bootstrap = createBootstrap(script);
  assert.match(bootstrap, /pasi-userscript-main/);
  assert.match(bootstrap, /GM\.unsafeWindow = globalThis/);
  assert.doesNotMatch(bootstrap, /chrome\.runtime\.sendMessage\(\{source:"pasi-userscript"/);
});

test('world configuration and MAIN execution remain separated', () => {
  assert.match(runtimeSource, /if \(script\.world !== 'USER_SCRIPT'\) return;/);
  assert.match(runtimeSource, /world:script\.world/);
  assert.match(runtimeSource, /worldId = 'pasi-us-' \+ script\.id/);
});

test('MAIN world is blocked unless explicit confirmation is recorded', () => {
  const {normalizeScript, parseMetadata} = loadUtils();
  const source = [
    '// ==UserScript==',
    '// @name Page',
    '// @match https://example.com/*',
    '// @grant unsafeWindow',
    '// @world MAIN',
    '// ==/UserScript=='
  ].join('\n');
  const script = normalizeScript(source, parseMetadata(source), null, false);
  assert.equal(script.unsafeConfirmed, false);
});

test('DNR-backed GM_webRequest is bounded and persisted per script', () => {
  assert.match(runtimeSource, /MAX_NETWORK_RULES = 50/);
  assert.match(runtimeSource, /MAX_NETWORK_RULE_BYTES = 20 \* 1024/);
  assert.match(runtimeSource, /DNR_STORE_PREFIX/);
  assert.match(runtimeSource, /webRequest\.rules/);
  assert.match(runtimeSource, /clearNetworkRules/);
  assert.match(runtimeSource, /restoreNetworkRules/);
});

test('bridge only forwards authenticated main-world RPCs to the extension', () => {
  assert.match(bridgeSource, /pasi-userscript-main/);
  assert.match(bridgeSource, /pasi-userscript-main-response/);
  assert.match(bridgeSource, /pasi-userscript-bridge-init/);
  assert.match(bridgeSource, /pasi-userscript-bridge/);
  assert.match(bridgeSource, /PASI userscript extension context invalidated/);
  assert.match(bridgeSource, /PASI userscript bridge authentication failed/);
});
