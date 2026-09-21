'use strict';
/*
 * P1-A core: progress-based recovery decision logic for automation/chromium/pasi-chatgpt/recovery.js.
 *
 * Pure, DOM-free decision logic + a small tracker + an optional MutationObserver hookup.
 *
 * Rule: never recover on age alone.
 *   recover when  (connection-error banner)
 *              or (stop button present AND no observable progress for stallMs)
 *              or (operation age >= hardCeilingMs)          <- last resort only
 *   never recover across a security/auth challenge (human boundary) or once the reload budget is spent.
 *
 * WHY A HARD CEILING EXISTS: progress detection depends on DOM heuristics (indicator text, text length).
 * If ChatGPT changes its DOM so that a *stalled* page keeps emitting "progress" (e.g. a ticking animation
 * text), the stall rule alone could never fire. The ceiling bounds that failure mode so a 168h run cannot hang
 * indefinitely on one operation. It is deliberately far above the longest legitimate Thinking answers.
 */

const RECOVERY_DEFAULTS = Object.freeze({
  stallMs: 8 * 60 * 1000,        // no-progress window while generation appears active
  hardCeilingMs: 90 * 60 * 1000, // absolute last-resort ceiling (see above)
  maxReloads: 1,                 // preserves existing MAX_RELOADS semantics
  sampleThrottleMs: 250,         // min gap between DOM samples driven by mutations
  backstopPollMs: 5000           // bounded polling fallback if mutations are missed/throttled
});

function resolveRecoveryConfig(overrides = {}) {
  const cfg = { ...RECOVERY_DEFAULTS };
  for (const key of Object.keys(overrides || {})) {
    if (!(key in RECOVERY_DEFAULTS)) throw new Error(`unknown recovery config key: ${key}`);
    cfg[key] = overrides[key];
  }
  for (const key of ['stallMs', 'hardCeilingMs', 'sampleThrottleMs', 'backstopPollMs']) {
    if (!Number.isFinite(cfg[key]) || cfg[key] <= 0) throw new Error(`${key} must be a positive number`);
  }
  if (!Number.isInteger(cfg.maxReloads) || cfg.maxReloads < 0) throw new Error('maxReloads must be an integer >= 0');
  if (cfg.stallMs >= cfg.hardCeilingMs) throw new Error('stallMs must be smaller than hardCeilingMs');
  return Object.freeze(cfg);
}

// Elapsed-time counters ("Thinking for 12m 4s") tick forever even when a page is stalled, so they must not count as progress.
// Only time-like tokens are stripped; bare numbers (e.g. "3 sources") still count as a change.
const TIME_TOKEN = /\b\d+(?:[.:]\d+)*\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|ms|s|m|h)\b/gi;
function normalizeIndicator(text) {
  return String(text || '').replace(TIME_TOKEN, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

class ProgressTracker {
  constructor(startMs) {
    this.lastProgressMs = startMs;
    this.nodeId = null;
    this.maxLength = 0;
    this.indicator = null;
  }
  // sample: { nodeId, length, indicator } describing the NEWEST assistant node. Returns true if it is real progress.
  observe(sample, nowMs) {
    if (!sample) return false;
    const indicator = normalizeIndicator(sample.indicator);
    let progress = false;
    if (sample.nodeId !== this.nodeId) {            // a new generation node appeared
      this.nodeId = sample.nodeId;
      this.maxLength = 0;
      this.indicator = indicator;
      progress = true;
    } else if (indicator !== this.indicator) {      // reasoning phase/summary text changed (timers stripped)
      this.indicator = indicator;
      progress = true;
    }
    const length = Number(sample.length) || 0;
    if (length > this.maxLength) {                  // output grew; shrink/re-render at same size is NOT progress
      this.maxLength = length;
      progress = true;
    }
    if (progress) this.lastProgressMs = nowMs;
    return progress;
  }
}

function decideRecovery(input, config = RECOVERY_DEFAULTS) {
  const { nowMs, startedMs, lastProgressMs, generating, connectionError, securityChallenge, reloadCount } = input;
  const age = nowMs - startedMs;
  const idle = nowMs - lastProgressMs;
  const detail = { ageMs: age, idleMs: idle };
  if (securityChallenge) return { recover: false, reason: 'human_boundary', ...detail };
  if (reloadCount >= config.maxReloads) return { recover: false, reason: 'reload_budget_exhausted', ...detail };
  if (connectionError) return { recover: true, reason: 'connection_error', ...detail };
  if (age >= config.hardCeilingMs) return { recover: true, reason: 'hard_ceiling', ...detail };
  if (generating && idle >= config.stallMs) return { recover: true, reason: 'no_progress', ...detail };
  return { recover: false, reason: 'none', ...detail };
}

// MutationObserver primary signal + bounded polling backstop. Attributes are NOT observed, so style/class churn
// never wakes the sampler, and unchanged samples never count as progress (see ProgressTracker).
function attachProgressObserver({ root, readSample, onSample, config = RECOVERY_DEFAULTS, now = Date.now, MutationObserverImpl = globalThis.MutationObserver, setIntervalImpl = setInterval, clearIntervalImpl = clearInterval }) {
  let last = -Infinity;
  const run = () => { last = now(); onSample(readSample(), last); };
  const observer = new MutationObserverImpl(() => { if (now() - last >= config.sampleThrottleMs) run(); });
  observer.observe(root, { subtree: true, childList: true, characterData: true });
  const timer = setIntervalImpl(run, config.backstopPollMs);
  run();
  return { detach() { observer.disconnect(); clearIntervalImpl(timer); } };
}

const PASI_RECOVERY_PROGRESS_API = Object.freeze({
  RECOVERY_DEFAULTS,
  resolveRecoveryConfig,
  normalizeIndicator,
  ProgressTracker,
  decideRecovery,
  attachProgressObserver
});
if (typeof globalThis !== 'undefined') globalThis.PASI_RECOVERY_PROGRESS = PASI_RECOVERY_PROGRESS_API;
if (typeof module !== 'undefined' && module.exports) module.exports = PASI_RECOVERY_PROGRESS_API;