(() => {
  'use strict';

  const RAM_WARNING_RATIO = 0.90;
  const PROFILE_NOTES = {
    satellite: 'Conservative profile. UI preference only; runtime safety limits remain authoritative.',
    'local-workstation': 'Balanced profile. UI preference only; runtime safety limits remain authoritative.',
    'bare-metal-beast': 'High-throughput profile. UI preference only; runtime safety limits remain authoritative.'
  };

  const bridgeGet = (path) => new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: 'pasi-control-center-bridge-request', method: 'GET', path },
      (response) => {
        const error = chrome.runtime.lastError;
        if (error) return reject(new Error(error.message || 'extension messaging failed'));
        if (!response?.ok) return reject(new Error('bridge request failed'));
        try { resolve(JSON.parse(response.text || 'null')); }
        catch (parseError) { reject(parseError); }
      }
    );
  });

  function byId(id) { return document.getElementById(id); }

  function applyRamWarning(resources) {
    const used = Number(resources?.memory_used_mib);
    const total = Number(resources?.memory_mib);
    const ratio = total > 0 ? used / total : NaN;
    const panel = byId('pasi-control-center');
    const note = byId('ram-warning');
    if (!panel || !note) return;
    const warning = Number.isFinite(ratio) && ratio >= RAM_WARNING_RATIO;
    panel.dataset.ramWarning = warning ? 'true' : 'false';
    note.hidden = !warning;
    note.textContent = warning ? 'RAM pressure high: ' + Math.round(ratio * 100) + '% of reported memory is in use.' : '';
  }

  function updateLatency(data) {
    const value = Number(data?.response_to_next_prompt_ms ?? data?.response_to_next_dispatch_ms ?? data?.latency_metrics?.response_to_next_prompt_ms);
    const node = byId('latency-metric');
    if (!node || !Number.isFinite(value) || value < 0) return;
    node.textContent = Math.round(value) + ' ms';
  }

  function updateProvider(runner, status) {
    const node = byId('provider-metric');
    if (!node) return;
    const provider = String(runner?.last_provider || status?.last_provider || 'primary').trim();
    node.textContent = provider ? provider.toUpperCase() : 'PRIMARY';
  }

  function updateDissectionProgress() {
    chrome.storage.local.get('pasi:control-center').then((stored) => {
      const value = stored?.['pasi:control-center'];
      const progress = Number(value?.dissection?.progress);
      const pass = Number(value?.dissection?.pass);
      const label = byId('dissection-pass');
      if (label && pass > 0 && Number.isFinite(progress)) label.textContent = 'Pass ' + pass + ' · local roadmap state ' + Math.round(progress) + '%';
    }).catch(() => {});
  }

  function wireProfileNotes() {
    const select = byId('hardware-profile');
    const note = byId('profile-note');
    if (!select || !note) return;
    const update = () => { note.textContent = PROFILE_NOTES[select.value] || PROFILE_NOTES.satellite; };
    select.addEventListener('change', update);
    update();
  }

  async function refreshEnhancements() {
    try {
      const [browser, capabilities, runner, status] = await Promise.all([
        bridgeGet('/browser/observation'),
        bridgeGet('/runner/capabilities'),
        bridgeGet('/runner/state'),
        bridgeGet('/status')
      ]);
      const observation = browser?.observation ?? browser;
      const data = observation?.data ?? observation;
      applyRamWarning(capabilities?.resources);
      updateLatency(data);
      updateProvider(runner, status);
    } catch (_) {
      const panel = byId('pasi-control-center');
      if (panel) panel.dataset.ramWarning = 'false';
    }
    updateDissectionProgress();
  }

  function init() {
    wireProfileNotes();
    void refreshEnhancements();
    setInterval(() => { void refreshEnhancements(); }, 5000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();