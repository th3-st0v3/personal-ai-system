const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const ROOT = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'manifest.json'), 'utf8'));
const background = fs.readFileSync(path.join(ROOT, 'background.js'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'sidepanel.html'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'sidepanel.css'), 'utf8');
const script = fs.readFileSync(path.join(ROOT, 'sidepanel.js'), 'utf8');

test('native extension manifest exposes the side panel without broadening page permissions', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.ok(manifest.permissions.includes('sidePanel'));
  assert.ok(manifest.permissions.includes('storage'));
  assert.deepEqual(manifest.side_panel, { default_path: 'sidepanel.html' });
  assert.equal(manifest.action.default_title, 'Open PASI Control Center');
  assert.ok(!manifest.permissions.includes('webRequest'));
  assert.ok(!manifest.permissions.includes('scripting'));
  assert.ok(!manifest.permissions.includes('activeTab'));
});

test('background opens the side panel from the extension action and keeps control-center bridge routes narrow', () => {
  assert.match(background, /chrome\.sidePanel\.setPanelBehavior\(\{ openPanelOnActionClick: true \}\)/);
  assert.match(background, /pasi-control-center-bridge-request/);
  assert.match(background, /\/runner\/capabilities/);
  assert.match(background, /POST \/runner\/control/);
  assert.match(background, /chrome-extension:\/\/\$\{chrome\.runtime\.id\}/);
});

test('side panel shell is self-contained and does not load remote assets', () => {
  assert.match(html, /<title>PASI Control Center<\/title>/);
  assert.match(html, /sidepanel\.css/);
  assert.match(html, /sidepanel\.js/);
  assert.doesNotMatch(html, /<(?:script|link|img|iframe)\b[^>]+https?:\/\//i);
});

test('side panel includes accessible roadmap import, keyboard reorder, telemetry, and resource controls', () => {
  assert.match(html, /id="btn-import"/);
  assert.match(html, /id="roadmap-text"/);
  assert.match(html, /id="roadmap-file"/);
  assert.match(html, /id="task-list"/);
  assert.match(html, /id="hardware-profile"/);
  assert.match(html, /id="telemetry-heading"/);
  assert.match(html, /id="automation-state"/);
  assert.match(script, /data-move="up"/);
  assert.match(script, /ArrowUp/);
  assert.match(script, /ArrowDown/);
  assert.match(script, /draggable="true"/);
});

test('side panel keeps drag/drop as a preference while rejecting dependency-violating orders', () => {
  assert.match(script, /orderSatisfiesDependencies/);
  assert.match(script, /violat(e|es) a dependency|dependency/);
  assert.match(script, /Planner remains authoritative/);
  assert.match(script, /Hybrid Planner remains authoritative/);
});

test('side panel bounds raw roadmap storage before persisting local state', () => {
  assert.match(script, /MAX_RAW_ROADMAP_CHARS = 500000/);
  assert.match(script, /raw\.length > MAX_RAW_ROADMAP_CHARS/);
});

test('side panel stores raw roadmap input locally and does not pretend cloud dissection is already connected', () => {
  assert.match(script, /pasi:control-center/);
  assert.match(script, /state\.rawRoadmap = raw/);
  assert.match(script, /Raw roadmap imported; ready for dissection/);
  assert.match(script, /Structured roadmap imported; awaiting planner handoff/);
  assert.match(html, /ready for a later dissection adapter/);
});

test('side panel telemetry reads only the existing bridge health contracts', () => {
  assert.match(script, /pasi-control-center-bridge-request/);
  assert.match(script, /bridgeGet\('\/status'\)/);
  assert.match(script, /bridgeGet\('\/browser\/observation'\)/);
  assert.match(script, /chrome\.storage\.local/);
  assert.doesNotMatch(script, /fetch\(['"]https?:\/\//);
});

test('side panel does not implement network stream interception or privileged runner process control', () => {
  assert.doesNotMatch(script, /EventSource|ReadableStream|webRequest|declarativeNetRequest|chrome\.debugger|exec|spawn|pkill|kill\(/);
  assert.doesNotMatch(manifest.host_permissions.join(' '), /<all_urls>/);
});

test('side panel respects reduced-motion preferences in its stylesheet', () => {
  assert.match(css, /prefers-reduced-motion/);
});

test('side panel JavaScript syntax is valid', () => {
  assert.doesNotThrow(() => require('node:child_process').execFileSync(process.execPath, ['--check', path.join(ROOT, 'sidepanel.js')]));
});


test('side panel exposes live runner capability and safe control contracts', () => {
  assert.match(html, /id="runner-metric"/);
  assert.match(html, /id="ram-metric"/);
  assert.match(html, /id="btn-retry-current"/);
  assert.match(html, /id="btn-panic-stop"/);
  assert.match(script, /bridgeGet\('\/runner\/capabilities'\)/);
  assert.match(script, /bridgeGet\('\/runner\/state'\)/);
  assert.match(script, /bridgePost\('\/runner\/control'/);
  assert.match(script, /retry_current/);
  assert.match(script, /action === 'stop'/);
  assert.doesNotMatch(script, /<all_urls>/);
});

test('side panel persists local refresh settings', () => {
  assert.match(html, /id="settings-dialog"/);
  assert.match(html, /id="telemetry-interval"/);
  assert.match(script, /telemetryIntervalMs/);
  assert.match(script, /1000, 5000, 10000, 30000/);
});
