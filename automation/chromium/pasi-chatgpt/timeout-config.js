(() => {
  'use strict';

  const DEFAULTS = Object.freeze({
    heartbeatMs: 5 * 1000,
    staleMs: 15 * 1000,
    pollMs: 500,
    domPollMs: 20,
    menuMs: 5000,
    composerMs: 10000,
    sendMs: 5000,
    submitMs: 2500,
    generationMs: 60 * 60 * 1000,
    recoveryTriggerMs: 60 * 60 * 1000,
    recoveryGraceMs: 600 * 1000,
    recoveryStallMs: 8 * 60 * 1000,
    recoveryHardCeilingMs: 90 * 60 * 1000,
    recoveryProgressSampleMs: 250,
    recoveryProgressPollMs: 5000,
    clickSettleMs: 20,
    thinkingVerifyMs: 3000,
    responseSettleMs: 10,
    submissionAckMs: 1000
  });

  let policy = { ...DEFAULTS };

  function validNumber(value) {
    return Number.isFinite(value) && value > 0;
  }

  function fromJson(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const next = {
      heartbeatMs: Number(raw.heartbeat_seconds) * 1000,
      staleMs: Number(raw.stale_seconds) * 1000,
      pollMs: Number(raw.controller_poll_ms),
      domPollMs: Number(raw.dom_poll_ms),
      menuMs: Number(raw.menu_ms),
      composerMs: Number(raw.composer_ms),
      sendMs: Number(raw.send_ms),
      submitMs: Number(raw.submit_ms),
      generationMs: Number(raw.generation_seconds) * 1000,
      recoveryTriggerMs: Number(raw.recovery_trigger_seconds) * 1000,
      recoveryGraceMs: Number(raw.recovery_grace_seconds) * 1000,
      recoveryStallMs: Number(raw.recovery_stall_seconds) * 1000,
      recoveryHardCeilingMs: Number(raw.recovery_hard_ceiling_seconds) * 1000,
      recoveryProgressSampleMs: Number(raw.recovery_progress_sample_ms),
      recoveryProgressPollMs: Number(raw.recovery_progress_poll_ms),
      clickSettleMs: Number(raw.click_settle_ms),
      thinkingVerifyMs: Number(raw.thinking_verify_ms),
      responseSettleMs: Number(raw.response_settle_ms),
      submissionAckMs: Number(raw.submission_ack_ms)
    };
    if (!Object.values(next).every(validNumber)) return null;
    if (next.staleMs < next.heartbeatMs * 3) return null;
    if (next.generationMs < next.recoveryTriggerMs) return null;
    if (next.recoveryStallMs >= next.recoveryHardCeilingMs) return null;
    return next;
  }

  async function load() {
    try {
      const response = await fetch(chrome.runtime.getURL('timeout-policy.json'), { cache: 'no-store' });
      if (!response.ok) return policy;
      const parsed = fromJson(await response.json());
      if (parsed) policy = parsed;
    } catch (_) {}
    return policy;
  }

  globalThis.PASI_TIMEOUT_POLICY = Object.freeze({
    defaults: DEFAULTS,
    get: () => policy,
    load
  });
  void load();
})();
