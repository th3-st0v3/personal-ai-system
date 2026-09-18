(() => {
  'use strict';

  const ACTIVE_KEY = 'pasi:active-operation';
  const HOST_ID = 'pasi-activity-indicator';
  const POLL_MS = 2000;
  const STYLE = `
    :host { all: initial; }
    .shell {
      position: fixed;
      left: 50%;
      bottom: 24px;
      transform: translateX(-50%);
      z-index: 2147483647;
      display: none;
      align-items: center;
      gap: 10px;
      min-width: 164px;
      max-width: min(360px, calc(100vw - 32px));
      padding: 9px 14px 9px 10px;
      border: 1px solid rgba(255, 255, 255, 0.72);
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(225,229,235,0.96) 52%, rgba(198,203,210,0.96));
      box-shadow: 0 10px 30px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.92);
      color: #20242a;
      font: 600 13px/1.1 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0.01em;
      user-select: none;
      pointer-events: none;
      backdrop-filter: blur(16px) saturate(120%);
      overflow: hidden;
    }
    .shell::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(105deg, transparent 20%, rgba(255,255,255,0.84) 46%, transparent 72%);
      transform: translateX(-130%);
      animation: pasi-shimmer 2.4s ease-in-out infinite;
    }
    .orb {
      position: relative;
      width: 24px;
      height: 24px;
      flex: 0 0 24px;
      border-radius: 50%;
      background: radial-gradient(circle at 32% 28%, #fff 0 18%, #f4f6f8 34%, #c7ccd3 68%, #9ea5ae 100%);
      box-shadow: 0 0 0 1px rgba(255,255,255,0.82), 0 0 18px rgba(255,255,255,0.9), 0 2px 8px rgba(50,55,62,0.22);
      animation: pasi-pulse 1.65s ease-in-out infinite;
    }
    .orb::before,
    .orb::after {
      content: '';
      position: absolute;
      border-radius: 50%;
      inset: -4px;
      border: 1px solid rgba(255,255,255,0.65);
      animation: pasi-ring 1.65s ease-out infinite;
    }
    .orb::after { animation-delay: 0.55s; }
    .copy { position: relative; z-index: 1; display: grid; gap: 3px; min-width: 0; }
    .label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta { color: #606770; font-size: 11px; font-weight: 500; }
    @keyframes pasi-pulse {
      0%, 100% { transform: scale(0.94); filter: brightness(0.98); }
      50% { transform: scale(1.05); filter: brightness(1.06); }
    }
    @keyframes pasi-ring {
      0% { transform: scale(0.8); opacity: 0.72; }
      100% { transform: scale(1.5); opacity: 0; }
    }
    @keyframes pasi-shimmer {
      0%, 18% { transform: translateX(-130%); }
      58%, 100% { transform: translateX(130%); }
    }
    @media (prefers-reduced-motion: reduce) {
      .shell::after, .orb, .orb::before, .orb::after { animation: none; }
    }
    @media (max-width: 520px) {
      .shell { bottom: 16px; min-width: 0; width: auto; }
    }
  `;

  let host = null;
  let shell = null;
  let label = null;
  let meta = null;
  let operationId = null;
  let startedAt = 0;
  let sawGeneration = false;

  function generating() {
    return Boolean(document.querySelector(
      'button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label*="Stop"]'
    ));
  }

  function getActiveOperation() {
    try {
      const value = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      return value?.operation_id ? value : null;
    } catch (_) {
      return null;
    }
  }

  function ensureUi() {
    if (host?.isConnected) return;
    host = document.createElement('div');
    host.id = HOST_ID;
    host.setAttribute('aria-hidden', 'true');
    const shadow = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = STYLE;
    shell = document.createElement('div');
    shell.className = 'shell';
    shell.innerHTML = `
      <span class="orb" aria-hidden="true"></span>
      <span class="copy">
        <span class="label"></span>
        <span class="meta"></span>
      </span>
    `;
    shadow.append(style, shell);
    label = shell.querySelector('.label');
    meta = shell.querySelector('.meta');
    document.documentElement.appendChild(host);
  }

  function formatElapsed(start) {
    const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
    if (seconds < 1) return 'just started';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${minutes}m ${String(remainder).padStart(2, '0')}s`;
  }

  function sync() {
    ensureUi();
    const active = getActiveOperation();
    if (!active) {
      operationId = null;
      startedAt = 0;
      sawGeneration = false;
      shell.style.display = 'none';
      return;
    }

    if (active.operation_id !== operationId) {
      operationId = active.operation_id;
      startedAt = Date.parse(active.started_at || '') || Date.now();
      sawGeneration = false;
    }

    const isGenerating = generating();
    if (isGenerating) sawGeneration = true;
    const state = isGenerating ? 'Thinking' : sawGeneration ? 'Finishing' : 'Working';
    label.textContent = `PASI · ${state}`;
    meta.textContent = formatElapsed(startedAt);
    shell.style.display = 'flex';
  }

  function start() {
    sync();
    setInterval(sync, POLL_MS);
  }

  start();
})();
