const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'chatgpt-runtime-watchdog.user.js'), 'utf8');

test('watchdog declares a version and localhost bridge contract', () => {
    assert.match(source, /@version\s+1\.0\.0/);
    assert.match(source, /127\.0\.0\.1:8765/);
    assert.match(source, /\/browser\/observation/);
});

test('watchdog distinguishes context exhaustion from provider usage limits', () => {
    assert.match(source, /conversation has reached its limit/);
    assert.match(source, /current usage limit/);
    assert.match(source, /provider_usage_limited: providerUsageLimited/);
    assert.match(source, /conversation_context_exhausted: contextExhausted/);
});

test('watchdog reports authentication challenges and Thinking state without changing the page', () => {
    assert.match(source, /auth_required: authRequired/);
    assert.match(source, /thinking_enabled: inferThinkingEnabled\(\)/);
    assert.doesNotMatch(source, /\.click\(\)/);
});

test('watchdog samples runtime health on a bounded cadence', () => {
    assert.match(source, /var INTERVAL_MS = 20000;/);
    assert.match(source, /setInterval\(sample, INTERVAL_MS\)/);
    assert.match(source, /kind: 'chatgpt_health'/);
    assert.match(source, /captured_at/);
});
