(() => {
  'use strict';

  const CONTROLLER_VERSION = '2.4.11';
  const TIMEOUT_POLICY = globalThis.PASI_TIMEOUT_POLICY?.get?.() || {};
  const POLL_MS = TIMEOUT_POLICY.pollMs || 500;
  const HEALTH_MS = Math.min(TIMEOUT_POLICY.heartbeatMs || 5000, 5000);
  const DOM_POLL_MS = TIMEOUT_POLICY.domPollMs || 20;
  const CLICK_SETTLE_MS = TIMEOUT_POLICY.clickSettleMs || 20;
  const THINKING_VERIFY_MS = TIMEOUT_POLICY.thinkingVerifyMs || 3000;
  const RESPONSE_SETTLE_MS = TIMEOUT_POLICY.responseSettleMs || 20;
  const PREVIOUS_RESPONSE_WAIT_MS = 5 * 60 * 1000;
  const GENERATION_START_WAIT_MS = 30 * 1000;
  const MAX_RESPONSE_TEXT_CHARS = 120_000;
  const SUBMISSION_ACK_MS = TIMEOUT_POLICY.submissionAckMs || 1000;
  const RESPONSE_TELEMETRY_DEFER_MS = 100;
  const SUBMISSION_ATTEMPTS = 3;
  const COMPLETION_RETRY_DELAY_MS = 20;
  const TIMEOUTS = {
    menu: TIMEOUT_POLICY.menuMs || 8000,
    composer: TIMEOUT_POLICY.composerMs || 15000,
    send: TIMEOUT_POLICY.sendMs || 10000,
    submit: TIMEOUT_POLICY.submitMs || 5000,
    generation: TIMEOUT_POLICY.generationMs || 60 * 60 * 1000
  };
  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const RECOVERY_OPERATION_KEY = 'recovery_operation_id';
  const RECOVERY_RESUME_OPERATION_KEY = 'resume_operation_id';
  const MAX_CONTEXT_AUTO_RECOVERIES = 1;
  const MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS = 200;
  let activeOperationId = null;
  let processing = false;
  let reasoningMode = null;
  let githubAttached = false;
  let githubRepository = null;
  let lastKnownChatUrl = null;
  let extensionContextInvalidated = false;
  let controllerLeader = false;
  let leaseTimerId = null;
  let controllerClaimedAt = 0;
  const CONTROLLER_CLAIM_CACHE_MS = 2000;
  let pollTimerId = null;
  let healthTimerId = null;
  let healthReportInFlight = null;
  let pollInFlight = null;
  let lastStateReportAt = 0;
  const STATE_REPORT_MS = 10000;
  let immediatePollQueued = false;
  let immediateOperationQueued = false;
  let lastCompletionAckAtMs = 0;
  let activeRecoveryState = null;

  function scheduleImmediateOperation(operation) {
    if (immediateOperationQueued || extensionContextInvalidated || !operation?.operation_id) return;
    immediateOperationQueued = true;
    queueMicrotask(() => {
      immediateOperationQueued = false;
      if (!processing && activeOperationId === null && !extensionContextInvalidated) {
        void processOperation(operation);
      }
    });
  }

  function scheduleImmediatePoll() {
    if (immediatePollQueued || extensionContextInvalidated) return;
    immediatePollQueued = true;
    queueMicrotask(() => {
      immediatePollQueued = false;
      if (!processing && activeOperationId === null && !extensionContextInvalidated) void poll();
    });
  }


  function isExtensionContextInvalidatedError(error) {
    return /extension context invalidated|context invalidated/i.test(String(error?.message || error));
  }

  function markThinkingUnavailable(reason) {
    reasoningMode = 'unavailable';
    void reportObservation('chatgpt_reasoning_capability', {
      chat_url: chatUrl(),
      thinking_available: false,
      reasoning_mode: 'unavailable',
      reason: String(reason || 'current account/model does not expose a Thinking option').slice(0, 500),
      native_controller: true
    });
    return false;
  }

  async function bridge(path, options = {}) {
    if (extensionContextInvalidated) {
      throw new Error('PASI_NATIVE: extension context invalidated; reload the ChatGPT page');
    }
    if (!globalThis.chrome?.runtime?.sendMessage) {
      throw new Error('PASI_NATIVE: extension messaging API unavailable');
    }
    const timeoutMs = Number(options.timeout || 10000);
    return new Promise((resolve, reject) => {
      let settled = false;
      const timerId = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error('PASI_NATIVE: bridge message timed out'));
      }, timeoutMs);
      try {
        chrome.runtime.sendMessage({
          type: 'pasi-bridge-request',
          path: String(path || ''),
          method: String(options.method || 'GET').toUpperCase(),
          body: options.body ?? null,
          timeout: timeoutMs
        }, (response) => {
          if (settled) return;
          settled = true;
          clearTimeout(timerId);
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError) {
            const message = String(runtimeError.message || '');
            if (/extension context invalidated|context invalidated/i.test(message)) {
              extensionContextInvalidated = true;
              reject(new Error('PASI_NATIVE: extension context invalidated; reload the ChatGPT page'));
              return;
            }
            reject(new Error('PASI_NATIVE: extension bridge error: ' + message));
            return;
          }
          if (!response || typeof response !== 'object') {
            reject(new Error('PASI_NATIVE: invalid bridge response'));
            return;
          }
          const text = typeof response.text === 'string' ? response.text : '';
          const error = typeof response.error === 'string' ? response.error : '';
          resolve({
            ok: response.ok === true,
            status: Number(response.status || 0),
            text,
            error,
            json: () => JSON.parse(text)
          });
        });
      } catch (error) {
        if (settled) return;
        settled = true;
        clearTimeout(timerId);
        reject(error);
      }
    });
  }  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* Event-driven waits: MutationObserver reacts immediately; the interval is only a backstop. */
  function waitUntil(predicate, timeoutMs, pollMs = DOM_POLL_MS) {
    return new Promise((resolve) => {
      let done = false;
      let checkQueued = false;
      let observer = null;
      let interval = null;
      let timeout = null;
      const finish = (value) => {
        if (done) return;
        done = true;
        if (observer) observer.disconnect();
        if (interval !== null) clearInterval(interval);
        if (timeout !== null) clearTimeout(timeout);
        resolve(value);
      };
      const check = () => {
        checkQueued = false;
        if (done) return;
        try {
          const value = predicate();
          if (value) finish(value);
        } catch (_) {}
      };
      const scheduleCheck = () => {
        if (done || checkQueued) return;
        checkQueued = true;
        queueMicrotask(check);
      };
      const root = document.documentElement || document;
      if (typeof MutationObserver === 'function' && root) {
        observer = new MutationObserver(scheduleCheck);
        try {
          observer.observe(root, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: [
              'aria-checked',
              'aria-current',
              'aria-disabled',
              'aria-haspopup',
              'aria-labelledby',
              'aria-pressed',
              'aria-selected',
              'class',
              'data-active',
              'data-checked',
              'data-selected',
              'data-state',
              'data-testid',
              'disabled',
              'hidden',
              'role',
              'style',
              'title'
            ],
            characterData: true
          });
        } catch (_) {
          observer = null;
        }
      }
      interval = setInterval(scheduleCheck, pollMs);
      timeout = setTimeout(() => finish(null), timeoutMs);
      scheduleCheck();
    });
  }

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && element.getClientRects().length > 0;
  }

  function disabled(element) {
    return Boolean(element) && (
      element.disabled === true ||
      element.hasAttribute?.('disabled') ||
      element.getAttribute('aria-disabled') === 'true'
    );
  }

  function label(element) {
    if (!element) return '';
    const labelledBy = element.getAttribute?.('aria-labelledby');
    const labelledText = labelledBy
      ? labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ')
      : '';
    return normalize([
      element.getAttribute?.('aria-label'),
      element.getAttribute?.('title'),
      labelledText,
      element.textContent
    ].filter(Boolean).join(' '));
  }

  function firstVisible(selectors, requireEnabled = false) {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (visible(element) && (!requireEnabled || !disabled(element))) return element;
      }
    }
    return null;
  }

  function findLabeled(labels, selectors, requireEnabled = false) {
    const needles = labels.map(normalize);
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!visible(element) || (requireEnabled && disabled(element))) continue;
        const text = label(element);
        if (needles.some((needle) => text === needle || text.startsWith(needle + ' ') || text.includes(' ' + needle))) return element;
      }
    }
    return null;
  }

  function composer() {
    return firstVisible(['#prompt-textarea', 'textarea[data-id="root"]', 'textarea', '[contenteditable="true"][role="textbox"]', '[contenteditable="true"]']);
  }

  function isTextControl(element) { return element?.tagName === 'TEXTAREA' || element?.tagName === 'INPUT'; }

  function setNativeValue(element, value) {
    const prototype = Object.getPrototypeOf(element);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
    if (descriptor?.set) descriptor.set.call(element, value);
    else element.value = value;
  }

  function setText(element, value) {
    element.focus();
    if (isTextControl(element)) {
      setNativeValue(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      return;
    }

    // Prefer the browser's editing command for contenteditable composers so
    // React/ProseMirror/Lexical-style editors receive the same editing path
    // as real user input instead of only seeing a DOM text mutation.
    let inserted = false;
    try {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(element);
      selection?.removeAllRanges();
      selection?.addRange(range);
      if (typeof document.execCommand === 'function') {
        inserted = document.execCommand('insertText', false, value);
      }
    } catch (_) {}

    if (!inserted) {
      element.textContent = value;
      const inputEvent = typeof InputEvent === 'function'
        ? new InputEvent('input', {
            bubbles: true,
            composed: true,
            inputType: 'insertText',
            data: value
          })
        : new Event('input', { bubbles: true, composed: true });
      element.dispatchEvent(inputEvent);
    }
    element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  }

  function insertText(element, text) { setText(element, text); }

  function readText(element) { return isTextControl(element) ? String(element.value || '') : String(element?.innerText || element?.textContent || ''); }

  function generating() {
    const stop = document.querySelector(
      'button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label*="Stop"]'
    );
    return visible(stop);
  }

  function chatUrl() { return /^https:\/\/chatgpt\.com(?::\d+)?\/c\//.test(location.href) ? location.href : null; }

  function detectorState() {
    return globalThis.PASIChatGPTDetectors?.detect?.() || {
      context_exhausted: false,
      usage_limited: false,
      auth_required: false,
      connection_failure: false
    };
  }

  function contextExhausted() {
    return detectorState().context_exhausted === true;
  }

  function hasFreshControllerLease() {
    return controllerLeader && Date.now() - controllerClaimedAt < CONTROLLER_CLAIM_CACHE_MS;
  }

  function controllerClaim({ force = false } = {}) {
    if (!globalThis.chrome?.runtime?.sendMessage) return Promise.resolve(false);
    const now = Date.now();
    if (!force && controllerLeader && now - controllerClaimedAt < CONTROLLER_CLAIM_CACHE_MS) {
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: 'pasi-controller-claim' }, (response) => {
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError || !response || response.ok !== true) {
            controllerLeader = false;
            controllerClaimedAt = 0;
            resolve(false);
            return;
          }
          controllerLeader = response.leader === true;
          controllerClaimedAt = controllerLeader ? Date.now() : 0;
          resolve(controllerLeader);
        });
      } catch (_) {
        controllerLeader = false;
        controllerClaimedAt = 0;
        resolve(false);
      }
    });
  }

  function usageLimited() {
    return !contextExhausted() && detectorState().usage_limited === true;
  }

  function authRequired() {
    return detectorState().auth_required === true;
  }

  function selectionState(element) {
    if (!element) return null;
    const values = [
      element.getAttribute('aria-pressed'),
      element.getAttribute('aria-selected'),
      element.getAttribute('aria-checked'),
      element.getAttribute('aria-current'),
      element.getAttribute('data-state'),
      element.getAttribute('data-selected'),
      element.getAttribute('data-checked'),
      element.getAttribute('data-active')
    ].filter(Boolean).map(normalize);

    if (values.some((value) => ['true', 'selected', 'checked', 'on', 'active', 'current', 'page'].includes(value))) return true;
    if (values.some((value) => ['false', 'unselected', 'unchecked', 'off', 'inactive'].includes(value))) return false;

    const className = typeof element.className === 'string' ? normalize(element.className) : '';
    if (/(^| )(selected|checked|active|enabled)( |$)/.test(className)) return true;
    if (/(^| )(unselected|unchecked|inactive|disabled)( |$)/.test(className)) return false;

    const accessible = label(element);
    if (/\b(selected|checked|current)\b/.test(accessible)) return true;
    if (/\b(not selected|unchecked|inactive|disabled)\b/.test(accessible)) return false;
    return null;
  }

  function modelModeFromLabel(value) {
    const text = normalize(value);
    if (!text) return null;
    if (
      /\b(?:thinking|think|medium|high|extra high|pro(?: standard| extended)?)\b/.test(text) ||
      /\bextended\b/.test(text)
    ) return 'thinking';
    if (/\binstant\b/.test(text)) return 'instant';
    if (/\bauto(?:matic)?\b/.test(text)) return 'auto';
    return null;
  }

  function findModelPill() {
    const preferredSelectors = [
      'button[data-testid*="model" i]',
      'button[aria-label*="model" i]',
      'button[title*="model" i]',
      'button[data-testid*="intelligence" i]',
      'button[aria-label*="intelligence" i]',
      'button.__composer-pill',
      '.__composer-pill'
    ];

    // ChatGPT may label the active selector with a model name (for example,
    // only "GPT-5") rather than the current reasoning mode. Prefer controls
    // whose metadata clearly identifies the model/intelligence switcher, then
    // fall back to a nearby menu button instead of requiring the word
    // "thinking" to already be present in its label.
    const candidates = [];
    const seen = new Set();
    const collect = (selector, scope = document) => {
      for (const element of scope.querySelectorAll(selector)) {
        if (seen.has(element) || !visible(element) || disabled(element)) continue;
        seen.add(element);
        candidates.push(element);
      }
    };

    const box = composer();
    const localScope = box?.closest?.('form') || box?.parentElement?.parentElement || null;
    for (const selector of preferredSelectors) {
      if (localScope) collect(selector, localScope);
      if (!candidates.length) collect(selector);
    }
    if (candidates.length) return candidates[0];

    // Last-resort compatibility path: a menu button adjacent to the composer
    // is more likely to be the model selector than an unrelated page menu.
    if (localScope) {
      collect('button[aria-haspopup="menu"], [role="button"][aria-haspopup="menu"]', localScope);
      if (candidates.length) return candidates[0];
    }

    return null;
  }

  function currentModelMode() {
    return modelModeFromLabel(label(findModelPill()));
  }

  function thinkingEnabled() {
    const currentMode = currentModelMode();
    if (currentMode === 'thinking') return true;
    if (currentMode === 'instant' || currentMode === 'auto') return false;

    const selected = document.querySelectorAll(
      '[aria-pressed], [aria-selected], [aria-checked], [aria-current], [data-state], [data-selected], [data-checked], [data-active]'
    );
    let explicitFalse = false;
    for (const element of selected) {
      if (!visible(element)) continue;
      const text = label(element);
      if (!/\b(?:thinking|think|medium|high|extra high|pro(?: standard| extended)?)\b/.test(text)) continue;
      const state = selectionState(element);
      if (state === true) return true;
      if (state === false) explicitFalse = true;
    }
    return explicitFalse ? false : null;
  }

  function userMessages() { return Array.from(document.querySelectorAll('[data-message-author-role="user"]')).filter(visible); }
  function assistantMessages() { return Array.from(document.querySelectorAll('[data-message-author-role="assistant"]')).filter(visible); }

  function messageText(node) {
    return String(node?.innerText || node?.textContent || '')
      .replace(/\r\n?/g, '\n')
      .replace(/[ \t]+(?=\n)/g, '')
      .trim();
  }

  function collapseWhitespace(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function snapshotUserMessages() {
    const nodes = userMessages();
    return {
      keys: new Set(nodes.map((node) => node.getAttribute?.('data-message-id')).filter(Boolean)),
      nodes: new WeakSet(nodes),
      count: nodes.length
    };
  }

  function promptFingerprints(prompt) {
    const text = normalize(prompt);
    return { head: text.slice(0, 80), tail: text.slice(-80) };
  }

  // returns 'match' | 'new_unmatched' | null
  function classifyNewUserMessages(nodes, snapshot, head, tail, textOf) {
    let unmatched = false;
    for (const node of nodes) {
      const key = node.getAttribute?.('data-message-id');
      const known = key ? snapshot.keys.has(key) : snapshot.nodes.has(node);
      if (known) continue;
      const text = normalize(textOf(node));
      if ((head && text.includes(head)) || (tail && text.includes(tail))) return 'match';
      unmatched = true;
    }
    return unmatched ? 'new_unmatched' : null;
  }

  function countNewUserMessages(nodes, snapshot) {
    let count = 0;
    for (const node of nodes) {
      const key = node.getAttribute?.('data-message-id');
      const known = key ? snapshot.keys.has(key) : snapshot.nodes.has(node);
      if (!known) count += 1;
    }
    return count;
  }

  function captureUiDiagnostics() {
    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
      .filter(visible).slice(0, 30)
      .map((element) => ({
        l: label(element).slice(0, 40),
        t: element.getAttribute('data-testid') || '',
        d: disabled(element) ? 1 : 0
      }));
    return {
      vis: document.visibilityState,
      gen: generating(),
      composer: Boolean(composer()),
      auth: authRequired(),
      limited: usageLimited(),
      exhausted: contextExhausted(),
      users: userMessages().length,
      assistants: assistantMessages().length,
      mode: reasoningMode,
      buttons
    };
  }

  function clearMonitoringStateFor(operationId) {
    try {
      const state = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      if (state && state.operation_id === operationId && state.phase === 'monitoring') localStorage.removeItem(RECOVERY_KEY);
    } catch (_) {}
  }

  function conversationSignature() {
    return `${userMessages().length}:${assistantMessages().length}:${fingerprint()}`;
  }

  function recoveryContext() {
    const context = {};
    if (reasoningMode === 'thinking') context.reasoning_mode = 'thinking';
    if (
      githubAttached &&
      typeof githubRepository === 'string' &&
      githubRepository.length <= MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS &&
      /^[^/\s]+\/[^/\s]+$/.test(githubRepository)
    ) {
      context.github_repository = githubRepository;
    }
    return Object.keys(context).length ? context : null;
  }

  async function reportObservation(kind, data, timeout = 10000) {
    try {
      await bridge('/browser/observation', {
        timeout,
        method: 'POST',
        body: { observation: {
          schema_version: 'pasi-native-chromium-v2',
          captured_at: new Date().toISOString(),
          data: { kind, controller_version: CONTROLLER_VERSION, ...data }
        } }
      });
    } catch (_) {}
  }

  function reportHealth() {
    if (healthReportInFlight) return healthReportInFlight;
    healthReportInFlight = (async () => {
      const currentUrl = chatUrl();
      if (currentUrl !== lastKnownChatUrl) {
        if (lastKnownChatUrl !== null || currentUrl !== null) {
          void reportObservation('chatgpt_chat_changed', {
            previous_chat_url: lastKnownChatUrl,
            new_chat_url: currentUrl,
            active_operation_id: activeOperationId,
            reason: processing ? 'during_operation' : 'navigation'
          }, 2000);
        }
        if (!processing) {
          githubAttached = false;
          githubRepository = null;
          reasoningMode = null;
        }
        lastKnownChatUrl = currentUrl;
      }

      // One detector pass per heartbeat. Repeated DOM scans here are
      // unnecessary and can compete with the prompt/response hot path.
      const detected = detectorState();
      const exhausted = detected.context_exhausted === true;
      const limited = !exhausted && detected.usage_limited === true;
      const auth = detected.auth_required === true;
      const thinking = thinkingEnabled();
      const composerPresent = Boolean(composer());

      // Health is the freshness signal used by the launcher/watchdog. Keep it
      // lightweight and bounded so DOM/state telemetry cannot delay it.
      await reportObservation('chatgpt_health', {
        chat_url: currentUrl,
        provider_usage_limited: limited,
        auth_required: auth,
        conversation_context_exhausted: exhausted,
        thinking_enabled: thinking,
        thinking_capability: reasoningMode === 'unavailable' ? 'unavailable' : (thinking === true ? 'available' : 'unknown'),
        page_visible: document.visibilityState !== 'hidden',
        composer_present: composerPresent,
        native_controller: true,
        active_operation_id: activeOperationId
      }, 2000);

      if (Date.now() - lastStateReportAt >= STATE_REPORT_MS) {
        lastStateReportAt = Date.now();
        // State telemetry includes a conversation fingerprint and is therefore
        // intentionally decoupled from the fast health heartbeat.
        void reportObservation('chatgpt_state', {
          chat_url: currentUrl,
          conversation_context_exhausted: exhausted,
          chat_exhausted: exhausted,
          provider_usage_limited: limited,
          github_attached: githubAttached,
          reasoning_mode: reasoningMode,
          reasoning_capability: reasoningMode === 'unavailable' ? 'unavailable' : (thinking === true ? 'available' : 'unknown'),
          conversation_signature: conversationSignature(),
          active_operation_id: activeOperationId,
          native_controller: true
        });
      }
    })().finally(() => {
      healthReportInFlight = null;
    });
    return healthReportInFlight;
  }

  async function waitFor(select, timeout) {
    return waitUntil(select, timeout, DOM_POLL_MS);
  }

  function findNewChatControl() {
    const exactSelectors = [
      'button[data-testid="new-chat-button"]',
      '[data-testid="new-chat-button"]',
      'button[aria-label="New chat"]',
      '[role="button"][aria-label="New chat"]'
    ];
    for (const selector of exactSelectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!visible(element) || disabled(element)) continue;
        if (element.closest?.('nav, aside, [role="navigation"]')) continue;
        return element;
      }
    }
    for (const element of document.querySelectorAll('button, [role="button"], a')) {
      if (!visible(element) || disabled(element)) continue;
      if (element.closest?.('nav, aside, [role="navigation"]')) continue;
      if (label(element) === 'new chat') return element;
    }
    return null;
  }

  async function newChat() {
    const previousLocation = location.href;
    const previousChat = chatUrl();
    const previousSignature = conversationSignature();
    const button = await waitFor(() => findLabeled(['new chat'], ['a', 'button', '[role="button"]']), TIMEOUTS.menu);
    if (!button || disabled(button)) throw new Error('PASI_NATIVE: New chat control unavailable');
    button.click();

    const ready = await waitFor(() => {
      const currentChat = chatUrl();
      const navigated = location.href !== previousLocation;
      const differentChat = Boolean(previousChat && currentChat && currentChat !== previousChat);
      const initialChatReady = !previousChat && navigated && currentChat && composer() && !generating() && userMessages().length === 0 && assistantMessages().length === 0 && conversationSignature() !== previousSignature;
      return composer() && !generating() && (differentChat || initialChatReady);
    }, TIMEOUTS.menu + 7000);
    if (!ready) throw new Error('PASI_NATIVE: new chat did not reach a verified ready state');

    const current = chatUrl();
    if (previousChat && (!current || current === previousChat)) throw new Error('PASI_NATIVE: new chat control did not change conversation identity');
    reasoningMode = null;
    githubAttached = false;
    githubRepository = null;
    lastKnownChatUrl = current;
  }

  function isReasoningLabel(value) {
    const text = normalize(value);
    return /\b(?:thinking|think|medium|high|extra high|pro(?: standard| extended)?)\b/.test(text) ||
      /\bextended\b/.test(text);
  }

  function findThinkingMenuOption() {
    const modal = firstVisible(['[data-testid="modal-intelligence-menu"]']);
    if (modal) {
      const radios = modal.querySelectorAll('button[role="radio"], [role="radio"]');
      for (const element of radios) {
        if (visible(element) && isReasoningLabel(label(element))) return element;
      }
    }

    const menus = document.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"]');
    for (const menu of menus) {
      if (!visible(menu)) continue;
      const candidates = menu.querySelectorAll('[role="radio"], [role="option"], [role="menuitemradio"], [role="menuitem"], button');
      for (const element of candidates) {
        if (visible(element) && isReasoningLabel(label(element))) return element;
      }
    }
    return null;
  }

  function findDirectThinkingControl() {
    const exactLabels = new Set([
      'thinking',
      'think',
      'medium',
      'high',
      'extra high',
      'pro standard',
      'pro extended'
    ]);
    const controls = document.querySelectorAll(
      'button, [role="button"], [role="option"], [role="menuitem"], [role="menuitemradio"], [role="radio"]'
    );
    for (const element of controls) {
      if (!visible(element) || disabled(element)) continue;
      const text = label(element);
      if (exactLabels.has(text)) return element;
    }
    return null;
  }

  async function selectThinking() {
    const initialState = thinkingEnabled();
    if (initialState === true) { reasoningMode = 'thinking'; return; }

    // Free/Go and some newer ChatGPT layouts expose a direct Think control in
    // the composer menu rather than a Thinking option in the model picker.
    // Check that control before opening the model picker so an already-enabled
    // reasoning mode is not misclassified as unavailable.
    const directThinkingControl = findDirectThinkingControl();
    if (directThinkingControl) {
      const state = selectionState(directThinkingControl);
      if (state === true) {
        reasoningMode = 'thinking';
        return;
      }
      if (state === false) {
        directThinkingControl.click();
        await sleep(CLICK_SETTLE_MS);
        const verified = await waitFor(
          () => thinkingEnabled() === true ? true : null,
          THINKING_VERIFY_MS
        );
        if (!verified) throw new Error('PASI_NATIVE: Thinking selection could not be verified after direct Think control');
        reasoningMode = 'thinking';
        return;
      }
    }

    const pill = findModelPill();
    if (pill) {
      const mode = currentModelMode();
      if (mode === 'thinking') { reasoningMode = 'thinking'; return; }

      pill.click();
      await sleep(CLICK_SETTLE_MS);

      const configure = await waitFor(
        () => firstVisible(['[data-testid="model-configure-modal"]']) ||
          findLabeled(['configure'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]']),
        TIMEOUTS.menu
      );

      if (configure && visible(configure)) {
        configure.click();
        await sleep(CLICK_SETTLE_MS);
      }

      const thinkingOption = await waitFor(findThinkingMenuOption, TIMEOUTS.menu);
      if (!thinkingOption || disabled(thinkingOption)) {
        return markThinkingUnavailable('current ChatGPT account/model does not expose a usable Thinking model option');
      }

      const optionState = selectionState(thinkingOption);
      if (optionState === true) {
        await waitFor(() => currentModelMode() === 'thinking' || thinkingEnabled() === true ? true : null, 3000);
      } else {
        thinkingOption.click();
      }

      const verified = await waitFor(
        () => currentModelMode() === 'thinking' || thinkingEnabled() === true ? true : null,
        5000
      );
      if (!verified) throw new Error('PASI_NATIVE: Thinking selection could not be verified after model selection');
      reasoningMode = 'thinking';
      return;
    }

    const control = findLabeled(
      ['thinking', 'think', 'thinking mode'],
      ['button', '[role="button"]', '[role="option"]', '[role="menuitem"]', '[role="radio"]']
    );

    if (control && !disabled(control)) {
      const state = selectionState(control);
      if (state === true) {
        reasoningMode = 'thinking';
        return;
      }
      if (state === false) {
        control.click();
        await sleep(CLICK_SETTLE_MS);
        const verified = await waitFor(() => thinkingEnabled() === true ? true : null, THINKING_VERIFY_MS);
        if (!verified) throw new Error('PASI_NATIVE: Thinking selection could not be verified after toggle');
        reasoningMode = 'thinking';
        return;
      }
      throw new Error('PASI_NATIVE: Thinking state is ambiguous; refusing to toggle the control');
    }

    const plus = await waitFor(
      () => firstVisible([
        'button[data-testid="composer-plus-btn"]',
        'button[aria-label="Add files and more"]',
        'button[aria-label*="Add files"]',
        'button[aria-label*="Attach"]'
      ]),
      TIMEOUTS.menu
    );
    if (!plus || disabled(plus)) throw new Error('PASI_NATIVE: Thinking/model selection control unavailable');
    plus.click();
    await sleep(CLICK_SETTLE_MS);

    const menuThinking = await waitFor(findThinkingMenuOption, TIMEOUTS.menu);
    if (!menuThinking || disabled(menuThinking)) {
      return markThinkingUnavailable('current ChatGPT menu does not expose a usable Thinking option');
    }
    const menuState = selectionState(menuThinking);
    if (menuState === true) {
      reasoningMode = 'thinking';
      return;
    }
    if (menuState === false) {
      menuThinking.click();
      await sleep(CLICK_SETTLE_MS);
      const verified = await waitFor(() => thinkingEnabled() === true ? true : null, THINKING_VERIFY_MS);
      if (!verified) throw new Error('PASI_NATIVE: Thinking selection could not be verified after menu selection');
      reasoningMode = 'thinking';
      return;
    }
    throw new Error('PASI_NATIVE: Thinking state is ambiguous; refusing to toggle the menu control');
  }

  async function attachGithub(repository) {
    repository = String(repository || '').trim();
    if (!/^[^/\s]+\/[^/\s]+$/.test(repository)) {
      throw new Error('PASI_NATIVE: GitHub repository must be in owner/name form');
    }
    if (githubAttached) {
      if (githubRepository === repository) return;
      throw new Error('PASI_NATIVE: GitHub attachment conflicts with the requested repository');
    }
    const plus = await waitFor(() => firstVisible(['button[aria-label="Add files and more"]', 'button[aria-label*="Add files"]', 'button[aria-label*="Attach"]']), TIMEOUTS.menu);
    if (!plus || disabled(plus)) throw new Error('PASI_NATIVE: GitHub menu unavailable');
    plus.click();
    const github = await waitFor(() => findLabeled(['github'], ['button', '[role="button"]', '[role="menuitem"]', '[role="option"]']), TIMEOUTS.menu);
    if (!github) throw new Error('PASI_NATIVE: GitHub app unavailable');
    github.click();
    const picker = await waitFor(() => firstVisible(['input[placeholder*="repository" i]', 'input[placeholder*="repo" i]', '[role="dialog"] input[type="text"]']), TIMEOUTS.menu);
    if (!picker) throw new Error('PASI_NATIVE: repository picker unavailable');
    setText(picker, repository);
    const result = await waitFor(() => findLabeled([repository], ['button', '[role="button"]', '[role="option"]', '[role="menuitem"]', 'a']), TIMEOUTS.menu);
    if (!result) throw new Error('PASI_NATIVE: requested repository unavailable');
    result.click();
    await sleep(CLICK_SETTLE_MS);
    const bodyText = normalize(document.body?.innerText || '');
    const githubFailureMarkers = [
      'github connection failed',
      'github connection error',
      'failed to connect to github',
      'could not connect to github',
      'unable to connect to github',
      'github connection is unavailable',
      'github access is unavailable',
      'github access failed',
      'github authentication required',
      'github authentication failed',
      'reconnect github',
      'connect your github account',
      'github needs to be connected',
      'github app connection failed'
    ];
    if (githubFailureMarkers.some((marker) => bodyText.includes(marker))) {
      throw new Error('PASI_NATIVE: GitHub connection/access unavailable');
    }
    githubAttached = true;
    githubRepository = repository;
  }

  async function restoreRecoveryContext(context) {
    if (!context || typeof context !== 'object') return;

    const reasoning = normalize(context.reasoning_mode);
    if (reasoning) {
      if (reasoning !== 'thinking' && reasoning !== 'think') {
        throw new Error('PASI_NATIVE: unsupported recovery reasoning mode');
      }
      if (thinkingEnabled() !== true) {
        const selected = await selectThinking();
        if (selected === false && reasoningMode !== 'unavailable') {
          throw new Error('PASI_NATIVE: Thinking state could not be selected during recovery');
        }
      }
    }

    const repository = String(context.github_repository || '').trim();
    if (!repository) return;
    if (repository.length > MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS || !/^[^/\s]+\/[^/\s]+$/.test(repository)) {
      throw new Error('PASI_NATIVE: invalid recovery GitHub repository');
    }
    if (githubAttached && githubRepository !== repository) {
      throw new Error('PASI_NATIVE: recovery GitHub context conflicts with the current attachment');
    }
    if (!githubAttached) await attachGithub(repository);
  }

  function assistants() { return assistantMessages(); }

  function extractAssistant(node) {
    const markdown = Array.from(node.querySelectorAll?.('.markdown, [class*="markdown"]') || []).filter(visible);
    for (let i = markdown.length - 1; i >= 0; i -= 1) {
      const text = String(markdown[i].innerText || markdown[i].textContent || '')
        .replace(/\r\n?/g, '\n')
        .replace(/[ \t]+(?=\n)/g, '')
        .trim();
      if (text) return text.slice(0, MAX_RESPONSE_TEXT_CHARS);
    }
    return messageText(node).slice(0, MAX_RESPONSE_TEXT_CHARS);
  }

  function latestAssistant() {
    const nodes = document.querySelectorAll('[data-message-author-role="assistant"]');
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      if (visible(nodes[index])) return extractAssistant(nodes[index]);
    }
    return '';
  }

  function fingerprintFromText(value) {
    return collapseWhitespace(value).slice(-4000);
  }

  function fingerprint() { return fingerprintFromText(latestAssistant()); }

  function nearbyScopedControls(box) {
    const controls = [];
    const seen = new Set();
    let scope = box?.parentElement || null;

    // ChatGPT has used both form-owned and generic submit controls over time.
    // Walk only a few ancestors from the active composer so a fallback cannot
    // bind to an unrelated form elsewhere on the page.
    for (let depth = 0; scope && depth < 5; depth += 1, scope = scope.parentElement) {
      const candidates = scope.querySelectorAll(
        'button[data-testid*="send" i], button[aria-label*="send" i], button[title*="send" i]'
      );
      for (const element of candidates) {
        if (seen.has(element) || !visible(element) || disabled(element)) continue;
        seen.add(element);
        controls.push(element);
      }

      const submits = Array.from(scope.querySelectorAll('button[type="submit"]')).filter(
        (element) => visible(element) && !disabled(element) && !seen.has(element)
      );
      if (submits.length === 1) {
        seen.add(submits[0]);
        controls.push(submits[0]);
      } else if (submits.length > 1 && depth > 0) {
        // Do not guess among multiple generic submit buttons in a wider
        // ancestor; the exact composer-scoped selectors above remain safe.
        break;
      }
    }
    return controls;
  }

  function sendCandidatesForComposer(box) {
    const form = box?.closest?.('form') || null;
    const scope = form || document;
    const selectors = [
      'button[data-testid="send-button"]',
      'button[aria-label="Send prompt"]',
      'button[aria-label="Send message"]'
    ];
    const candidates = [];
    for (const selector of selectors) {
      candidates.push(...scope.querySelectorAll(selector));
    }

    // Generic submit controls are safe only when owned by the exact composer
    // form or uniquely identified within a small ancestor scope around it.
    if (form) {
      candidates.push(...form.querySelectorAll('button[type="submit"]'));
    }
    candidates.push(...nearbyScopedControls(box));

    const seen = new Set();
    return candidates.filter((element) => {
      if (seen.has(element)) return false;
      seen.add(element);
      return visible(element) && !disabled(element);
    });
  }

  function labeledSendInScope(scope) {
    if (!scope) return null;
    const elements = scope.querySelectorAll('button, [role="button"]');
    for (const element of elements) {
      if (!visible(element) || disabled(element)) continue;
      const text = label(element);
      if (['send prompt', 'send message', 'send'].some((needle) =>
        text === needle || text.startsWith(needle + ' ') || text.includes(' ' + needle)
      )) {
        return element;
      }
    }
    return null;
  }

  async function waitForSend(box) {
    return waitFor(() => {
      const candidates = sendCandidatesForComposer(box);
      if (candidates.length) return candidates[0];

      const form = box?.closest?.('form') || null;
      return labeledSendInScope(form || box?.parentElement || null);
    }, TIMEOUTS.send);
  }

  async function ensureThinkingBestEffort() {
    if (reasoningMode === 'thinking' || reasoningMode === 'unavailable') return reasoningMode;
    try {
      if (thinkingEnabled() === true) {
        reasoningMode = 'thinking';
        return reasoningMode;
      }
      await selectThinking();
      if (thinkingEnabled() === true) reasoningMode = 'thinking';
    } catch (error) {
      reasoningMode = 'unavailable';
      void reportObservation('chatgpt_reasoning_capability', {
        chat_url: chatUrl(),
        thinking_available: false,
        reasoning_mode: 'unavailable',
        reason: String(error?.message || error).slice(0, 300),
        native_controller: true
      });
      closeOpenMenus();
    }
    return reasoningMode;
  }

  function closeOpenMenus() {
    const target = document.activeElement || document.body;
    for (const type of ['keydown', 'keyup']) {
      target.dispatchEvent(new KeyboardEvent(type, {
        key: 'Escape',
        code: 'Escape',
        keyCode: 27,
        which: 27,
        bubbles: true,
        cancelable: true,
        composed: true
      }));
    }
  }

  async function ensurePromptSubmissionReady() {
    if (authRequired()) throw new Error('CHAT_AUTH_REQUIRED: interactive authentication/security verification is required');
    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
    await ensureThinkingBestEffort();
  }

  function composerContainsPrompt(element, expected) {
    return Boolean(element) && normalize(readText(element)).includes(normalize(expected));
  }

  function dispatchEnter(element) {
    element.focus();
    const init = {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true,
      cancelable: true,
      composed: true
    };
    element.dispatchEvent(new KeyboardEvent('keydown', init));
    element.dispatchEvent(new KeyboardEvent('keypress', init));
    element.dispatchEvent(new KeyboardEvent('keyup', { ...init, cancelable: false }));
  }

  function nativeMouseActivate(element) {
    if (!element) return false;
    element.focus();
    const init = {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      button: 0,
      buttons: 1,
      detail: 1
    };
    try {
      if (typeof PointerEvent === 'function') {
        element.dispatchEvent(new PointerEvent('pointerdown', { ...init, pointerId: 1, pointerType: 'mouse', isPrimary: true }));
      }
    } catch (_) {}
    element.dispatchEvent(new MouseEvent('mousedown', init));
    try {
      if (typeof PointerEvent === 'function') {
        element.dispatchEvent(new PointerEvent('pointerup', { ...init, pointerId: 1, pointerType: 'mouse', buttons: 0, isPrimary: true }));
      }
    } catch (_) {}
    element.dispatchEvent(new MouseEvent('mouseup', { ...init, buttons: 0 }));
    element.click();
    return true;
  }


  async function submitPrompt(expected) {
    const snapshot = snapshotUserMessages();
    const { head, tail } = promptFingerprints(expected);
    const newMessageState = () => classifyNewUserMessages(userMessages(), snapshot, head, tail, messageText);
    const accepted = () => {
      const state = newMessageState();
      if (state === 'match') return 'verified';
      if (state === 'new_unmatched' && generating()) return 'new_message_generating';
      return null;
    };

    const strategies = [
      async (box, button) => {
        if (generating()) return false;
        const form = (button || box).closest?.('form') || box.closest?.('form') || null;
        if (!form || typeof form.requestSubmit !== 'function') return false;
        try {
          const type = String(button?.getAttribute?.('type') || 'submit').toLowerCase();
          if (!button || type === 'submit') form.requestSubmit(button || undefined);
          else form.requestSubmit();
          return true;
        } catch (_) {
          return false;
        }
      },
      async (_box, button) => {
        if (generating() || !button || disabled(button)) return false;
        nativeMouseActivate(button);
        return true;
      },
      async (box) => {
        if (generating() || !composerContainsPrompt(box, expected)) return false;
        dispatchEnter(box);
        return true;
      }
    ];

    for (let attempt = 1; attempt <= strategies.length; attempt += 1) {
      let via = accepted();
      if (via) return {
        via,
        attempt,
        verified: via === 'verified',
        timing: {
          injected_at_ms: null,
          ack_at_ms: Date.now(),
          user_messages_added: countNewUserMessages(userMessages(), snapshot),
          ack_verified: via === 'verified',
          submission_via: via
        }
      };

      await ensurePromptSubmissionReady();
      const box = composer();
      const composerEmptied = !box || !composerContainsPrompt(box, expected);
      if ((attempt > 1 && composerEmptied) || generating() || newMessageState()) {
        via = await waitUntil(accepted, SUBMISSION_ACK_MS, DOM_POLL_MS);
        return { via: via || 'sent_unverified', attempt, verified: via === 'verified' };
      }

      let readyBox = box;
      if (!readyBox) throw new Error('PASI_NATIVE: composer disappeared');

      if (!composerContainsPrompt(readyBox, expected)) {
        if (normalize(readText(readyBox))) {
          throw new Error('PASI_NATIVE: composer holds unrelated text; refusing to overwrite');
        }
        insertText(readyBox, expected);
        readyBox = await waitUntil(() => {
          const current = composer();
          return current && composerContainsPrompt(current, expected) ? current : null;
        }, 2000, DOM_POLL_MS) || composer();
      }

      if (!readyBox || !composerContainsPrompt(readyBox, expected)) {
        if (attempt < strategies.length) continue;
        throw new Error('PASI_NATIVE: composer lost the requested prompt before submission after bounded recovery');
      }

      const button = await waitForSend(readyBox);
      if (!button) {
        if (attempt < strategies.length) continue;
        throw new Error('PASI_NATIVE: send control unavailable');
      }

      // Once a send strategy has fired, never invoke another send mechanism:
      // the delayed acknowledgement may simply trail the real submission, and
      // a second click can duplicate work.
      const injectedAtMs = Date.now();
      const fired = await strategies[attempt - 1](readyBox, button);
      if (!fired) continue;

      via = await waitUntil(accepted, SUBMISSION_ACK_MS, DOM_POLL_MS);
      const finalVia = via || 'sent_unverified';
      return {
        via: finalVia,
        attempt,
        verified: via === 'verified',
        timing: {
          injected_at_ms: injectedAtMs,
          ack_at_ms: Date.now(),
          user_messages_added: countNewUserMessages(userMessages(), snapshot),
          ack_verified: via === 'verified',
          submission_via: finalVia
        }
      };
    }

    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
    throw new Error('PASI_NATIVE: prompt submission could not be verified after bounded attempts');
  }


  function operationPrompt(operation) {
    return `[PASI_OPERATION ${operation.operation_id}]\n${operation.prompt}`;
  }

  function completionMarkersSatisfied(responseText, markers) {
    const text = typeof responseText === 'string' ? responseText : '';
    if (!text.trim()) return false;
    const configured = Array.isArray(markers)
      ? markers
          .filter((marker) => typeof marker === 'string' && marker.trim())
          .map((marker) => marker.trim())
      : [];
    if (!configured.length) return true;
    const lines = text.split(/\r?\n/).map((line) => line.trim());
    return configured.some((marker) =>
      lines.some((line) => line === marker || line.startsWith(marker + ':'))
    );
  }

  async function waitForResponse(baseline, completionMarkers = []) {
    let sawGeneration = false;
    let generationEndedAt = 0;
    let failureReason = null;

    const response = await waitUntil(() => {
      // While generation is active, the stop control is the only state needed
      // for this hot loop. Avoid a full failure-marker DOM scan on every mutation.
      if (generating()) {
        sawGeneration = true;
        generationEndedAt = 0;
        return null;
      }

      const detected = detectorState();
      if (detected.context_exhausted === true) {
        failureReason = 'CHAT_EXHAUSTED: conversation context is exhausted';
        return null;
      }
      if (
        detected.context_exhausted !== true &&
        detected.usage_limited === true
      ) {
        failureReason = 'CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited';
        return null;
      }

      if (sawGeneration) {
        if (!generationEndedAt) generationEndedAt = Date.now();
        if (Date.now() - generationEndedAt < RESPONSE_SETTLE_MS) return null;
        const responseText = latestAssistant();
        return (
          responseText &&
          fingerprintFromText(responseText) !== baseline &&
          completionMarkersSatisfied(responseText, completionMarkers)
        ) ? responseText : null;
      }

      const current = fingerprint();
      if (current !== baseline && current) {
        const responseText = latestAssistant();
        return completionMarkersSatisfied(responseText, completionMarkers)
          ? responseText
          : null;
      }
      return null;
    }, TIMEOUTS.generation, DOM_POLL_MS);

    if (failureReason) throw new Error(failureReason);
    if (response) return response;
    throw new Error('PASI_NATIVE: ChatGPT generation timed out');
  }


  function rememberContextRecovery(operation, error) {
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
    } catch (_) {}

    const startedAt = typeof stored?.started_at === 'string'
      ? stored.started_at
      : new Date().toISOString();

    localStorage.setItem(RECOVERY_KEY, JSON.stringify({
      operation_id: operation.operation_id,
      operation_type: operation.operation_type,
      started_at: startedAt,
      started_ms: Date.parse(startedAt) || Date.now(),
      baseline: fingerprint(),
      chat_url: chatUrl(),
      recovery_context: recoveryContext(),
      reload_count: 0,
      phase: 'context_exhausted',
      error: String(error?.message || error)
    }));
  }

  function rememberResponseRecovery(operation, error) {
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
    } catch (_) {}

    const startedAt = typeof stored?.started_at === 'string'
      ? stored.started_at
      : new Date().toISOString();

    localStorage.setItem(RECOVERY_KEY, JSON.stringify({
      operation_id: operation.operation_id,
      operation_type: operation.operation_type,
      started_at: startedAt,
      started_ms: Date.parse(startedAt) || Date.now(),
      baseline: typeof stored?.baseline === 'string' ? stored.baseline : fingerprint(),
      chat_url: chatUrl(),
      recovery_context: recoveryContext(),
      reload_count: 0,
      phase: 'monitoring',
      error: String(error?.message || error),
      response_recovery: true
    }));
  }

  function completionProgress(responseText) {
    const text = typeof responseText === 'string' ? responseText : '';
    const statusMatch = text.match(/^PASI_RESULT_STATUS:\s*(.+)$/m);
    const progressMatch = text.match(/^PASI_RESULT_REPOSITORY_PROGRESS:\s*(.+)$/m);
    const nextTaskMatch = text.match(/^PASI_RESULT_NEXT_TASK:\s*(.+)$/m);
    return {
      completion_status: statusMatch ? statusMatch[1].trim().toLowerCase() : null,
      repository_progress: progressMatch ? progressMatch[1].trim().toLowerCase() : null,
      next_task: nextTaskMatch ? nextTaskMatch[1].trim() : null
    };
  }

  async function finishOperation(operationId, responseText = '', requireResponseText = false, timing = null) {
    if (requireResponseText && (typeof responseText !== 'string' || !responseText.trim())) {
      throw new Error('PASI_NATIVE: response text unavailable; completion acknowledgement withheld');
    }
    const body = {
      operation_id: operationId,
      chat_url: chatUrl(),
      response_text: responseText.slice(0, MAX_RESPONSE_TEXT_CHARS),
      response_text_available: typeof responseText === 'string' && Boolean(responseText.trim()),
      ack_only: true
    };
    if (timing && typeof timing === 'object') body.timing = timing;
    if (typeof responseText === 'string') Object.assign(body, completionProgress(responseText));
    const publishResponseTelemetry = () => {
      void reportObservation('chatgpt_response', {
        chat_url: body.chat_url,
        response_text: body.response_text,
        response_text_available: body.response_text_available,
        ...(typeof responseText === 'string' ? completionProgress(responseText) : {}),
        ...(body.timing ? { timing: body.timing } : {}),
        conversation_context_exhausted: contextExhausted(),
        chat_exhausted: contextExhausted(),
        provider_usage_limited: usageLimited(),
        active_operation_id: operationId
      }).catch(() => {});

      void reportObservation('chat_response_received', {
        operation_id: operationId,
        phase: 'response_complete',
        captured_at: new Date().toISOString()
      });
    };
    // The durable /chat/finished record already contains the authoritative response.
    // Keep duplicate telemetry out of the completion -> next-operation critical path.
    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const response = await bridge('/chat/finished', { method: 'POST', body });
        if (response.ok) {
          try {
            const payload = response.json();
            lastCompletionAckAtMs = Date.now();
            if (payload && typeof payload === 'object' && payload.next_operation && typeof payload.next_operation === 'object') {
              payload.next_operation.__pasi_completion_ack_at_ms = lastCompletionAckAtMs;
            }
            setTimeout(publishResponseTelemetry, RESPONSE_TELEMETRY_DEFER_MS);
            return payload;
          } catch (_) {
            return { ok: true, operation_id: operationId, status: 'completed' };
          }
        }
        lastError = new Error(`PASI_NATIVE: bridge completion failed: HTTP ${response.status}`);
      } catch (error) {
        lastError = error;
      }

      try {
        const operation = await bridge(`/operation?operation_id=${encodeURIComponent(operationId)}`);
        const payload = operation.ok ? operation.json() : null;
        if (
          payload?.operation?.status === 'completed' &&
          payload?.operation?.response_text_available === true &&
          typeof payload?.operation?.response_text === 'string' &&
          Boolean(payload.operation.response_text.trim())
) return payload;
      } catch (_) {}

      if (attempt < 3) await sleep(COMPLETION_RETRY_DELAY_MS);
    }
    publishResponseTelemetry();
    throw lastError || new Error('PASI_NATIVE: bridge completion failed');
  }

  async function failOperation(operationId, error) {
    try {
      const response = await bridge('/chat/failed', { method: 'POST', body: { operation_id: operationId, error: String(error?.message || error) } });
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  async function processOperation(operation) {
    activeOperationId = operation.operation_id;
    processing = true;
    if (leaseTimerId !== null) clearInterval(leaseTimerId);
    if (!hasFreshControllerLease()) {
      const claimed = await controllerClaim();
      if (!claimed) {
        activeOperationId = null;
        processing = false;
        return;
      }
    }
    leaseTimerId = setInterval(() => {
      controllerClaim({ force: true }).catch(() => {
        controllerLeader = false;
        controllerClaimedAt = 0;
      });
    }, 3000);
    activeRecoveryState = {
      operation_id: operation.operation_id,
      operation_type: operation.operation_type,
      started_at: new Date().toISOString(),
      chat_url: chatUrl(),
      reasoning_mode: reasoningMode,
      github_attached: githubAttached,
      github_repository: githubRepository
    };
    localStorage.setItem(ACTIVE_KEY, JSON.stringify(activeRecoveryState));
    let finalized = false;
    let chainedOperation = null;
    try {
      switch (operation.operation_type) {
        case 'new_chat': await newChat(); break;
        case 'select_reasoning': await ensureThinkingBestEffort(); break;
        case 'attach_github': await attachGithub(operation.prompt); break;
        case 'prompt': {
          await restoreRecoveryContext(operation.recovery_context);
          await ensureThinkingBestEffort();
          if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
          if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
          // Never inject into a composer while an earlier response is still generating.
          const box = await waitUntil(() => {
            const current = composer();
            return current && !generating() ? current : null;
          }, PREVIOUS_RESPONSE_WAIT_MS, DOM_POLL_MS);
          if (!box) throw new Error(generating() ? 'PASI_NATIVE: previous response still generating' : 'PASI_NATIVE: composer unavailable');
          const baseline = fingerprint();
          if (!activeRecoveryState || activeRecoveryState.operation_id !== operation.operation_id) {
            activeRecoveryState = {
              operation_id: operation.operation_id,
              operation_type: operation.operation_type,
              started_at: new Date().toISOString(),
              chat_url: chatUrl(),
              reasoning_mode: reasoningMode,
              github_attached: githubAttached,
              github_repository: githubRepository
            };
          }
          activeRecoveryState.baseline = baseline;
          localStorage.setItem(ACTIVE_KEY, JSON.stringify(activeRecoveryState));
          const promptText = operationPrompt(operation);
          const submission = await submitPrompt(promptText);
          const browserTiming = { ...(submission.timing || {}) };
          const previousCompletionAckAtMs = Number(operation.__pasi_completion_ack_at_ms);
          if (
            Number.isFinite(previousCompletionAckAtMs) &&
            typeof browserTiming.injected_at_ms === 'number' &&
            Number.isFinite(browserTiming.injected_at_ms)
          ) {
            browserTiming.completion_to_prompt_injected_ms = Math.max(
              0,
              browserTiming.injected_at_ms - previousCompletionAckAtMs
            );
            void reportObservation('pasi_latency_measurement', {
              operation_id: operation.operation_id,
              phase: 'completion_to_prompt_injected',
              elapsed_ms: browserTiming.completion_to_prompt_injected_ms,
              previous_completion_ack_at_ms: previousCompletionAckAtMs,
              prompt_injected_at_ms: browserTiming.injected_at_ms
            });
          }
          void reportObservation('prompt_injected', {
            operation_id: operation.operation_id,
            captured_at: new Date().toISOString(),
            submission_via: submission.via,
            submission_attempt: submission.attempt,
            submission_verified: submission.verified,
            timing: browserTiming
          });
          if (!submission.verified) {
            void reportObservation('chatgpt_submit_unverified', {
              operation_id: operation.operation_id,
              via: submission.via,
              attempt: submission.attempt
            });
          }
          let generationStartMs = null;
          if (!(await waitUntil(() => {
            const started = generating() || fingerprint() !== baseline;
            if (started && generationStartMs === null) generationStartMs = Date.now();
            return started;
          }, GENERATION_START_WAIT_MS, DOM_POLL_MS))) {
            throw new Error('PASI_NATIVE: submission accepted but generation did not start');
          }
          browserTiming.generation_start_ms = generationStartMs;
          const response = await waitForResponse(
            baseline,
            Array.isArray(operation.completion_markers)
              ? operation.completion_markers
              : []
          );
          browserTiming.completed_at_ms = Date.now();
          const completion = await finishOperation(operation.operation_id, response, true, browserTiming);
          chainedOperation = completion?.next_operation || null;
          finalized = true;
          return;
        }
        default: throw new Error(`PASI_NATIVE: unsupported operation ${operation.operation_type}`);
      }
      const completion = await finishOperation(operation.operation_id);
      chainedOperation = completion?.next_operation || null;
      finalized = true;
    } catch (error) {
      const errorMessage = String(error?.message || error);
      const contextRecoveryEligible =
        operation.operation_type === 'prompt' &&
        errorMessage.startsWith('CHAT_EXHAUSTED:') &&
        Number(operation.retry_count || 0) < MAX_CONTEXT_AUTO_RECOVERIES;

      const responseRecoveryEligible =
        operation.operation_type === 'prompt' &&
        (
          errorMessage.startsWith('PASI_NATIVE: response text unavailable;') ||
          errorMessage.startsWith('PASI_NATIVE: ChatGPT generation timed out')
        );

      if (contextRecoveryEligible) {
        activeRecoveryState = null;
        rememberContextRecovery(operation, error);
        finalized = false;
      } else if (responseRecoveryEligible) {
        activeRecoveryState = null;
        rememberResponseRecovery(operation, error);
        finalized = false;
      } else {
        const failure = (
          errorMessage.startsWith('CHAT_EXHAUSTED:') &&
          Number(operation.retry_count || 0) >= MAX_CONTEXT_AUTO_RECOVERIES
        )
          ? new Error('PASI_NATIVE: context recovery exhausted: ' + errorMessage)
          : error;
        const detail = errorMessage + ' | ui=' + JSON.stringify(captureUiDiagnostics()).slice(0, 1400);
        finalized = await failOperation(operation.operation_id, new Error(detail));
      }
      throw error;
    } finally {
      if (leaseTimerId !== null) {
        clearInterval(leaseTimerId);
        leaseTimerId = null;
      }
      if (!finalized) {
        controllerLeader = false;
        controllerClaimedAt = 0;
      }
      activeOperationId = null;
      processing = false;
      if (finalized) {
        localStorage.removeItem(ACTIVE_KEY);
        activeRecoveryState = null;
        if (recoveryResumeOperationId() === operation.operation_id) {
          localStorage.removeItem(RECOVERY_KEY);
        }
        clearMonitoringStateFor(operation.operation_id);
      }
      void reportHealth();
      if (finalized) {
        if (chainedOperation?.operation_id) scheduleImmediateOperation(chainedOperation);
        else scheduleImmediatePoll();
      }
    }
  }

  async function recoverInterruptedOperation() {
    try {
      const stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      if (!stored?.operation_id) return;
      const current = await bridge(`/operation?operation_id=${encodeURIComponent(stored.operation_id)}`);
      const payload = current.ok ? current.json() : null;
      const operation = payload?.operation;
      if (!operation) return;

      if (operation.status === 'completed') {
        const responseText = typeof operation.response_text === 'string' ? operation.response_text : '';
        // Persisted nonblank response text is the evidence. A stale
        // controller availability flag must not discard it during restart
        // reconciliation; blank text remains fail-closed.
        const responseAvailable = Boolean(responseText.trim());
        if (responseAvailable) {
          try {
            await finishOperation(stored.operation_id, responseText, true);
          } catch (_) {
            // Keep the active marker so the next controller start can reconcile again.
            return;
          }
        } else if (!generating()) {
          const baseline = typeof stored?.baseline === 'string' ? stored.baseline : fingerprint();
          const visibleResponse = latestAssistant();
          const visibleFingerprint = fingerprint();
          if (visibleResponse && visibleFingerprint !== baseline) {
            try {
              await finishOperation(stored.operation_id, visibleResponse, true);
            } catch (_) {
              // Keep the active marker so recovery.js can retry against the same operation.
              return;
            }
          }
        }
        localStorage.removeItem(ACTIVE_KEY);
      } else if (operation.status === 'failed' || operation.status === 'cancelled') {
        localStorage.removeItem(ACTIVE_KEY);
      }
      // Preserve non-terminal operations for the dedicated bounded recovery companion.
    } catch (_) {}
  }

  function recoveryOperationId() {
    try {
      const state = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      const value = state?.[RECOVERY_OPERATION_KEY] || state?.[RECOVERY_RESUME_OPERATION_KEY];
      return typeof value === 'string' && value.trim() ? value : null;
    } catch (_) {
      return null;
    }
  }

  function recoveryResumeOperationId() {
    try {
      const state = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      const value = state?.[RECOVERY_RESUME_OPERATION_KEY];
      return typeof value === 'string' && value.trim() ? value : null;
    } catch (_) {
      return null;
    }
  }

  function poll() {
    if (processing || activeOperationId !== null || extensionContextInvalidated) return Promise.resolve();
    if (pollInFlight) return pollInFlight;
    pollInFlight = (async () => {
      if (!(await controllerClaim())) return;
      try {
      const recoveryOperation = recoveryOperationId();
      if (localStorage.getItem(RECOVERY_KEY) && !recoveryOperation) return;

      const response = recoveryOperation
        ? await bridge('/chat/claim', {
            method: 'POST',
            body: { operation_id: recoveryOperation }
          })
        : await bridge('/next-operation');
      if (!response.ok) {
        if (recoveryOperation) {
          try {
            const current = await bridge(`/operation?operation_id=${encodeURIComponent(recoveryOperation)}`);
            const operation = current.ok ? current.json().operation : null;
            if (operation && ['completed', 'failed', 'cancelled'].includes(operation.status)) {
              localStorage.removeItem(RECOVERY_KEY);
            }
          } catch (_) {}
        }
        return;
      }
      const payload = response.json();
      if (payload?.operation) await processOperation(payload.operation);
      } catch (error) {
        if (isExtensionContextInvalidatedError(error)) {
          extensionContextInvalidated = true;
          if (pollTimerId !== null) clearInterval(pollTimerId);
          if (healthTimerId !== null) clearInterval(healthTimerId);
          return;
        }
        console.warn('[PASI native controller]', error);
        try { await reportHealth(); } catch (_) {}
      }
    })().finally(() => {
      pollInFlight = null;
    });
    return pollInFlight;
  }

  async function start() {
    // Start health reporting before any recovery or queue work. Freshness must
    // not depend on the duration of interrupted-operation reconciliation.
    pollTimerId = setInterval(poll, POLL_MS);
    healthTimerId = setInterval(reportHealth, HEALTH_MS);
    void reportHealth();
    if (extensionContextInvalidated) return;

    await recoverInterruptedOperation();
    if (extensionContextInvalidated) {
      if (pollTimerId !== null) clearInterval(pollTimerId);
      if (healthTimerId !== null) clearInterval(healthTimerId);
      pollTimerId = null;
      healthTimerId = null;
      return;
    }

    await poll();
    if (extensionContextInvalidated) {
      if (pollTimerId !== null) clearInterval(pollTimerId);
      if (healthTimerId !== null) clearInterval(healthTimerId);
      pollTimerId = null;
      healthTimerId = null;
    }
  }

  if (globalThis.PASI_NATIVE_TEST_HOOKS === true) {
    globalThis.PASI_NATIVE_TEST_API = Object.freeze({
      messageText,
      extractAssistant,
      fingerprint,
      composerContainsPrompt,
      userMessages,
      assistantMessages,
      conversationSignature,
      operationPrompt,
      findNewChatControl,
      detectorState,
      submitPrompt,
      waitForResponse
    });
  } else {
    start();
  }
})();
