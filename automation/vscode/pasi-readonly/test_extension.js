const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const source = fs.readFileSync(path.join(root, 'extension.js'), 'utf8');

test('VS Code integration is dependency-free and startup activated', () => {
  assert.equal(packageJson.main, './extension.js');
  assert.ok(packageJson.activationEvents.includes('onStartupFinished'));
  assert.doesNotMatch(source, /child_process|exec\(|spawn\(|createTerminal|sendText\(/);
});

test('VS Code integration publishes bounded state rather than file contents', () => {
  assert.match(source, /pasi-vscode-readonly-v1/);
  assert.match(source, /diagnosticCounts/);
  assert.match(source, /visibleTextEditors/);
  assert.match(source, /MAX_VISIBLE_EDITORS/);
  assert.doesNotMatch(source, /document\.getText\(\)/);
  assert.doesNotMatch(source, /selection\.text/);
});

test('VS Code integration writes atomically into PASI runtime state', () => {
  assert.match(source, /\.runtime/);
  assert.match(source, /\.tmp/);
  assert.match(source, /fs\.promises\.rename/);
  assert.match(source, /mode: 0o600/);
});
