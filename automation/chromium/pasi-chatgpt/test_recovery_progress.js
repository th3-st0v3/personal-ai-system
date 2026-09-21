'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RECOVERY_DEFAULTS: D, resolveRecoveryConfig, normalizeIndicator, ProgressTracker, decideRecovery, attachProgressObserver } = require('./recovery_progress.js');

const MIN = 60 * 1000;
const base = { generating: true, connectionError: false, securityChallenge: false, reloadCount: 0 };

// Drive a simulated timeline minute by minute; returns the first recover decision or null.
function simulate({ minutes, progressEveryMin, stopProgressAtMin = Infinity, extra = {} }) {
  const t = new ProgressTracker(0);
  let len = 0;
  for (let m = 1; m <= minutes; m += 1) {
    if (m % progressEveryMin === 0 && m < stopProgressAtMin) len += 200;   // output only grows while "progressing"
    t.observe({ nodeId: 'a1', length: len, indicator: 'drafting patch' }, m * MIN);
    const d = decideRecovery({ ...base, ...extra, nowMs: m * MIN, startedMs: 0, lastProgressMs: t.lastProgressMs }, D);
    if (d.recover) return { minute: m, ...d };
  }
  return null;
}

test('1. long generation with continuing progress is never reloaded (60+ min old)', () => {
  assert.equal(simulate({ minutes: 89, progressEveryMin: 1 }), null);
});

test('2. stalled generation (stop button present, no progress) recovers ~8 min after last progress, not before', () => {
  const r = simulate({ minutes: 89, progressEveryMin: 1, stopProgressAtMin: 10 });
  assert.equal(r.reason, 'no_progress');
  assert.equal(r.minute, 9 + 8); // last progress at minute 9 -> fires at 17
});

test('2b. no stall recovery when generation is not active', () => {
  const d = decideRecovery({ ...base, generating: false, nowMs: 30 * MIN, startedMs: 0, lastProgressMs: 0 }, D);
  assert.equal(d.recover, false);
});

test('3. connection-error banner triggers immediate recovery even with fresh progress', () => {
  const d = decideRecovery({ ...base, connectionError: true, nowMs: 2 * MIN, startedMs: 0, lastProgressMs: 2 * MIN }, D);
  assert.deepEqual([d.recover, d.reason], [true, 'connection_error']);
});

test('4. hard ceiling still recovers even while progress keeps arriving (bounds a mis-detected stall)', () => {
  const r = simulate({ minutes: 120, progressEveryMin: 1 });
  assert.deepEqual([r.reason, r.minute], ['hard_ceiling', 90]);
});

test('5. preserved boundaries: security challenge and spent reload budget never recover', () => {
  const past = { nowMs: 100 * MIN, startedMs: 0, lastProgressMs: 0 };
  assert.equal(decideRecovery({ ...base, ...past, securityChallenge: true, connectionError: true }, D).reason, 'human_boundary');
  assert.equal(decideRecovery({ ...base, ...past, reloadCount: 1 }, D).reason, 'reload_budget_exhausted');
});

test('6. DOM churn: unchanged samples, shrink/re-render, and ticking timers are not progress; growth is', () => {
  const t = new ProgressTracker(0);
  assert.equal(t.observe({ nodeId: 'a1', length: 100, indicator: 'Thinking for 1m 2s' }, 1000), true);   // first sight
  assert.equal(t.observe({ nodeId: 'a1', length: 100, indicator: 'Thinking for 1m 3s' }, 2000), false);  // timer tick only
  assert.equal(t.observe({ nodeId: 'a1', length: 100, indicator: 'Thinking for 9m 40s' }, 3000), false);
  assert.equal(t.observe({ nodeId: 'a1', length: 80, indicator: 'Thinking for 9m 41s' }, 4000), false);   // re-render smaller
  assert.equal(t.lastProgressMs, 1000);
  assert.equal(t.observe({ nodeId: 'a1', length: 101, indicator: 'Thinking for 9m 42s' }, 5000), true);   // real growth
  assert.equal(t.observe({ nodeId: 'a1', length: 101, indicator: 'Searching the web for 9m 43s' }, 6000), true); // phase changed
  assert.equal(t.observe({ nodeId: 'a2', length: 0, indicator: '' }, 7000), true);                        // new generation node
  assert.equal(normalizeIndicator('Thinking for 12m 4s'), 'thinking for');
  assert.equal(normalizeIndicator('Found 3 sources'), 'found 3 sources');
});

test('7. config is validated and overridable; ceiling must exceed stall window', () => {
  assert.equal(resolveRecoveryConfig({ stallMs: 5 * MIN }).stallMs, 5 * MIN);
  assert.throws(() => resolveRecoveryConfig({ stallMs: 100 * MIN }));
  assert.throws(() => resolveRecoveryConfig({ nope: 1 }));
  assert.throws(() => resolveRecoveryConfig({ stallMs: -1 }));
  assert.throws(() => resolveRecoveryConfig({ maxReloads: 1.5 }));
});

test('8. observer wiring: mutations sample (throttled), attributes not observed, backstop poll runs, detach cleans up', () => {
  let cb = null, opts = null, disconnected = false, cleared = 0, intervalFn = null;
  class FakeMO { constructor(fn) { cb = fn; } observe(_r, o) { opts = o; } disconnect() { disconnected = true; } }
  let clock = 1000; const samples = [];
  const h = attachProgressObserver({
    root: {}, readSample: () => ({ nodeId: 'a', length: clock }), onSample: (s, t) => samples.push([s.length, t]),
    config: { ...D, sampleThrottleMs: 250, backstopPollMs: 5000 }, now: () => clock, MutationObserverImpl: FakeMO,
    setIntervalImpl: (fn) => { intervalFn = fn; return 7; }, clearIntervalImpl: () => { cleared += 1; }
  });
  assert.equal(opts.attributes, undefined); assert.equal(opts.characterData, true);
  assert.equal(samples.length, 1);            // initial sample
  clock += 100; cb();  assert.equal(samples.length, 1);   // throttled
  clock += 200; cb();  assert.equal(samples.length, 2);   // past throttle
  clock += 10; intervalFn(); assert.equal(samples.length, 3); // backstop
  h.detach(); assert.ok(disconnected); assert.equal(cleared, 1);
});