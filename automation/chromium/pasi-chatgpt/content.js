(() => {
  'use strict';

  const CONTROLLER_VERSION = '2.4.11';
  const TIMEOUT_POLICY = globalThis.PASI_TIMEOUT_POLICY?.get?.() || globalThis.PASI_TIMEOUT_POLICY?.defaults || {};
  var POLL_MS = 500;
  POLL_MS = TIMEOUT_POLICY.pollMs || POLL_MS;
  const HEALTH_MS = TIMEOUT_POLICY.heartbeatMs || 15000;
  var DOM_POLL_MS = 20;
  DOM_POLL_MS = TIMEOUT_POLICY.domPollMs || DOM_POLL_MS;
  const CLICK_SETTLE_MS = TIMEOUT_POLICY.clickSettleMs || 20;
  const THINKING_VERIFY_MS = TIMEOUT_POLICY.thinkingVerifyMs || 3000;
  const RESPONSE_SETTLE_MS = TIMEOUT_POLICY.responseSettleMs || 20;
  const SUBMISSION_ACK_MS = TIMEOUT_POLICY.submissionAckMs || 1000;
  const SUBMISSION_ATTEMPTS = 3;
  const TIMEOUTS = {
    menu: TIMEOUT_POLICY.menuMs || 8000,
    composer: TIMEOUT_POLICY.composerMs || 15000,
    send: TIMEOUT_POLICY.sendMs || 10000,
    submit: TIMEOUT_POLICY.submitMs || 5000,
    generation: TIMEOUT_POLICY.generationMs || 1500 * 1000
  };
  const ACTIVE_KEY = 'pasi:active-operation';
  const RECOVERY_KEY = 'pasi:chatgpt-recovery';
  const RECOVERY_OPERATION_KEY = 'recovery_operation_id';
  const RECOVERY_RESUME_OPERATION_KEY = 'resume_operation_id';
  const MAX_CONTEXT_AUTO_RECOVERIES = 1;
  const MAX_RECOVERY_CONTEXT_REPOSITORY_CHARS = 200;
  let activeOperationId = null;
  let processing = false;
  let controllerLeader = false;
  let reasoningMode = null;
  let githubAttached = false;
  let githubRepository = null;
  let lastKnownChatUrl = null;
  let extensionContextInvalidated = false;
  let pollTimerId = null;
  let healthTimerId = null;
  let leaseTimerId = null;

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
          body: options.body ?? null
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

  function accessibilityHidden(element) {
    for (let current = element; current; current = current.parentElement) {
      if (
        current.getAttribute?.('aria-hidden') === 'true' ||
        current.hasAttribute?.('inert')
      ) return true;
    }
    return false;
  }

  function visible(element) {
    if (!element || accessibilityHidden(element)) return false;
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


  function readText(element) { return isTextControl(element) ? String(element.value || '') : String(element?.innerText || element?.textContent || ''); }

  function generating() {
    return Boolean(firstVisible(['button[data-testid="stop-button"]', 'button[aria-label="Stop generating"]', 'button[aria-label*="Stop"]']));
  }

  function chatUrl() { return /^https:\/\/chatgpt\.com(?::\d+)?\/c\//.test(location.href) ? location.href : null; }

  function freshChatSurface(previousLocation, previousChat) {
    if (!previousChat || location.href === previousLocation) return false;
    if (!/^https:\/\/chatgpt\.com(?::\d+)?\/?(?:\?.*)?$/.test(location.href)) return false;
    return Boolean(composer()) && !generating() && userMessages().length === 0 && assistantMessages().length === 0;
  }


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
  function controllerClaim() {
    if (!globalThis.chrome?.runtime?.sendMessage) return Promise.resolve(false);
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: 'pasi-controller-claim' }, (response) => {
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError || !response || response.ok !== true) {
            controllerLeader = false;
            resolve(false);
            return;
          }
          controllerLeader = response.leader === true;
          resolve(controllerLeader);
        });
      } catch (_) {
        controllerLeader = false;
        resolve(false);
      }
    });
  }


  function usageLimited() {
    const state = detectorState();
    return state.context_exhausted !== true && state.usage_limited === true;
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

  function newestUserMatches(expected, baselineCount) {
    const nodes = userMessages();
    if (nodes.length <= baselineCount) return false;
    const needle = normalize(expected);
    for (let index = nodes.length - 1; index >= baselineCount; index -= 1) {
      const text = normalize(messageText(nodes[index]));
      if (text === needle || text.includes(needle)) return true;
    }
    return false;
  }

  function conversationSignature() {
    return `${userMessages().length}:${assistantMessages().length}:${fingerprint()}`;
  }

  function userMessageExistsForOperation(operationId) {
    const needle = normalize(`[PASI_OPERATION ${operationId}]`);
    if (!needle) return false;
    return userMessages().some((node) => normalize(messageText(node)).includes(needle));
  }

  function readJsonStorage(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch (_) {
      return null;
    }
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

  async function reportObservation(kind, data) {
    try {
      await bridge('/browser/observation', {
        method: 'POST',
        body: { observation: {
          schema_version: 'pasi-native-chromium-v2',
          captured_at: new Date().toISOString(),
          data: { kind, controller_version: CONTROLLER_VERSION, ...data }
        } }
      });
    } catch (_) {}
  }

  async function reportHealth() {
    if (!(await controllerClaim())) return;
    const currentUrl = chatUrl();
    if (currentUrl !== lastKnownChatUrl) {
      if (lastKnownChatUrl !== null || currentUrl !== null) {
        await reportObservation('chatgpt_chat_changed', {
          previous_chat_url: lastKnownChatUrl,
          new_chat_url: currentUrl,
          active_operation_id: activeOperationId,
          reason: processing ? 'during_operation' : 'navigation'
        });
      }
      if (!processing) {
        githubAttached = false;
        githubRepository = null;
        reasoningMode = null;
      }
      lastKnownChatUrl = currentUrl;
    }

    const exhausted = contextExhausted();
    const limited = usageLimited();
    await reportObservation('chatgpt_health', {
      chat_url: currentUrl,
      provider_usage_limited: limited,
      auth_required: authRequired(),
      conversation_context_exhausted: exhausted,
      thinking_enabled: thinkingEnabled(),
      thinking_capability: reasoningMode === 'unavailable' ? 'unavailable' : (thinkingEnabled() === true ? 'available' : 'unknown'),
      page_visible: document.visibilityState !== 'hidden',
      composer_present: Boolean(composer()),
      native_controller: true,
      active_operation_id: activeOperationId
    });
    await reportObservation('chatgpt_state', {
      chat_url: currentUrl,
      conversation_context_exhausted: exhausted,
      chat_exhausted: exhausted,
      provider_usage_limited: limited,
      github_attached: githubAttached,
      reasoning_mode: reasoningMode,
      reasoning_capability: reasoningMode === 'unavailable' ? 'unavailable' : (thinkingEnabled() === true ? 'available' : 'unknown'),
      conversation_signature: conversationSignature(),
      active_operation_id: activeOperationId,
      native_controller: true
    });
  }

  async function waitFor(select, timeout) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      const value = select();
      if (value) return value;
      await sleep(DOM_POLL_MS);
    }
    return null;
  }

  function clearFocusBeforeActivation() {
    const active = document.activeElement;
    if (!active || active === document.body || active === document.documentElement) return;
    try { active.blur(); } catch (_) {}
  }

  function activateControl(element) {
    if (!element || !visible(element) || disabled(element)) return false;
    clearFocusBeforeActivation();
    try {
      element.click();
      const focused = document.activeElement;
      if (focused && accessibilityHidden(focused)) {
        try { focused.blur(); } catch (_) {}
      }
      return true;
    } catch (_) {
      return false;
    }
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
    const button = await waitFor(findNewChatControl, TIMEOUTS.menu);
    if (!button || disabled(button)) throw new Error('PASI_NATIVE: New chat control unavailable');
    if (!activateControl(button)) throw new Error('PASI_NATIVE: New chat control activation failed');

    const ready = await waitFor(() => {
      const currentChat = chatUrl();
      const navigated = location.href !== previousLocation;
      const emptySurface = Boolean(composer()) && !generating() && userMessages().length === 0 && assistantMessages().length === 0;
      const differentChat = Boolean(previousChat && currentChat && currentChat !== previousChat && emptySurface);
      const freshRootChat = freshChatSurface(previousLocation, previousChat);
      const initialChatReady = !previousChat && navigated && currentChat && emptySurface && conversationSignature() !== previousSignature;
      return emptySurface && (differentChat || freshRootChat || initialChatReady);
    }, TIMEOUTS.menu + 7000);
    if (!ready) throw new Error('PASI_NATIVE: new chat did not reach a verified ready state');

    const current = chatUrl();
    if (previousChat && current === previousChat) throw new Error('PASI_NATIVE: new chat control did not change conversation identity');
    if (previousChat && !current && !freshChatSurface(previousLocation, previousChat)) {
      throw new Error('PASI_NATIVE: new chat control did not reach a verified fresh chat surface');
    }
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
        if (!activateControl(directThinkingControl)) throw new Error('PASI_NATIVE: Thinking control activation failed');
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

      if (!activateControl(pill)) throw new Error('PASI_NATIVE: model selector activation failed');
      await sleep(CLICK_SETTLE_MS);

      const configure = await waitFor(
        () => firstVisible(['[data-testid="model-configure-modal"]']) ||
          findLabeled(['configure'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]']),
        TIMEOUTS.menu
      );

      if (configure && visible(configure)) {
        if (!activateControl(configure)) throw new Error('PASI_NATIVE: model configure control activation failed');
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
        if (!activateControl(thinkingOption)) throw new Error('PASI_NATIVE: Thinking option activation failed');
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
        if (!activateControl(control)) throw new Error('PASI_NATIVE: Thinking toggle activation failed');
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
    if (!activateControl(plus)) throw new Error('PASI_NATIVE: add-files control activation failed');
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
      if (!activateControl(menuThinking)) throw new Error('PASI_NATIVE: Thinking menu activation failed');
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
    if (!activateControl(plus)) throw new Error('PASI_NATIVE: add-files control activation failed');
    const github = await waitFor(() => findLabeled(['github'], ['button', '[role="button"]', '[role="menuitem"]', '[role="option"]']), TIMEOUTS.menu);
    if (!github) throw new Error('PASI_NATIVE: GitHub app unavailable');
    if (!activateControl(github)) throw new Error('PASI_NATIVE: GitHub control activation failed');
    const picker = await waitFor(() => firstVisible(['input[placeholder*="repository" i]', 'input[placeholder*="repo" i]', '[role="dialog"] input[type="text"]']), TIMEOUTS.menu);
    if (!picker) throw new Error('PASI_NATIVE: repository picker unavailable');
    setText(picker, repository);
    const result = await waitFor(() => findLabeled([repository], ['button', '[role="button"]', '[role="option"]', '[role="menuitem"]', 'a']), TIMEOUTS.menu);
    if (!result) throw new Error('PASI_NATIVE: requested repository unavailable');
    if (!activateControl(result)) throw new Error('PASI_NATIVE: repository result activation failed');
    await sleep(CLICK_SETTLE_MS);
    const githubState = detectorState();
    if (githubState.github_failure === true) {
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

  function extractAssistant(node) {
    const markdown = Array.from(node.querySelectorAll?.('.markdown, [class*="markdown"]') || []).filter(visible);
    for (let i = markdown.length - 1; i >= 0; i -= 1) {
      const text = String(markdown[i].innerText || markdown[i].textContent || '')
        .replace(/\r\n?/g, '\n')
        .replace(/[ \t]+(?=\n)/g, '')
        .trim();
      if (text) return text.slice(0, 50000);
    }
    return messageText(node).slice(0, 50000);
  }

  function latestAssistant() {
    const nodes = assistantMessages();
    return nodes.length ? extractAssistant(nodes[nodes.length - 1]) : '';
  }

  function fingerprint() {
    return collapseWhitespace(latestAssistant()).slice(-4000);
  }

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

  async function waitForSubmissionAck(expected, baselineUserCount) {
    const started = Date.now();
    while (Date.now() - started < SUBMISSION_ACK_MS) {
      // A submission acknowledgement must identify PASI's exact prompt. Merely
      // observing generation plus an increased user-message count can be caused
      // by another message and can falsely advance the controller into the
      // one-hour response wait.
      if (newestUserMatches(expected, baselineUserCount)) return true;
      await sleep(DOM_POLL_MS);
    }
    return false;
  }

  async function verifyThinkingState() {
    return waitFor(() => {
      const state = thinkingEnabled();
      return state === true ? true : null;
    }, THINKING_VERIFY_MS);
  }

  async function ensureThinkingReady() {
    let state = thinkingEnabled();
    if (state === true) {
      reasoningMode = 'thinking';
      return true;
    }
    if (reasoningMode === 'unavailable') return true;

    // The model selector can report null briefly while ChatGPT is closing
    // the intelligence menu. Give the DOM a chance to settle before trying
    // to toggle the control again.
    state = await verifyThinkingState();
    if (state) {
      reasoningMode = 'thinking';
      return true;
    }
    if (reasoningMode === 'unavailable') return true;

    for (let attempt = 1; attempt <= 2; attempt += 1) {
      const selected = await selectThinking();
      if (selected === false && reasoningMode === 'unavailable') return true;
      if (await verifyThinkingState()) {
        reasoningMode = 'thinking';
        return true;
      }
      if (attempt < 2) await sleep(CLICK_SETTLE_MS);
    }

    return false;
  }

  async function ensurePromptSubmissionReady() {
    if (authRequired()) throw new Error('CHAT_AUTH_REQUIRED: interactive authentication/security verification is required');
    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
    if (!(await ensureThinkingReady())) {
      throw new Error('PASI_NATIVE: Thinking state could not be verified before prompt submission');
    }
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
    clearFocusBeforeActivation();
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
    const focused = document.activeElement;
    if (focused && accessibilityHidden(focused)) {
      try { focused.blur(); } catch (_) {}
    }
    return true;
  }


  function operationPrompt(operation) {
    return `[PASI_OPERATION ${operation.operation_id}]\n${operation.prompt}`;
  }

  async function submitPrompt(expected) {
    const baselineUserCount = userMessages().length;

    for (let attempt = 1; attempt <= SUBMISSION_ATTEMPTS; attempt += 1) {
      // ChatGPT can rerender or replace the composer node during controlled
      // input updates. Confirm the message was not already accepted before
      // treating a missing composer value as a failure.
      if (newestUserMatches(expected, baselineUserCount)) return;

      if (generating() || userMessages().length > baselineUserCount) {
        if (await waitForSubmissionAck(expected, baselineUserCount)) return;
        throw new Error('PASI_NATIVE: prompt submission already appears to be in progress; refusing to reinsert');
      }

      await ensurePromptSubmissionReady();

      let box = composer();
      if (!box) throw new Error('PASI_NATIVE: composer disappeared');

      // Re-acquire the composer after readiness checks. Restore the requested
      // prompt only when the new composer is empty; never overwrite unrelated
      // text that may have been entered independently.
      if (!composerContainsPrompt(box, expected)) {
        const currentText = normalize(readText(box));
        if (!currentText) {
          setText(box, expected);
          box = await waitFor(
            () => {
              const current = composer();
              return current && composerContainsPrompt(current, expected) ? current : null;
            },
            2000
          ) || composer();
        }
      }

      if (newestUserMatches(expected, baselineUserCount)) return;

      if (!box || !composerContainsPrompt(box, expected)) {
        if (attempt < SUBMISSION_ATTEMPTS) {
          await sleep(DOM_POLL_MS + 50);
          continue;
        }
        throw new Error('PASI_NATIVE: composer lost the requested prompt before submission after bounded recovery');
      }

      const button = await waitForSend(box);
      const form = (button || box)?.closest?.('form') || box.closest?.('form') || null;

      if (form?.requestSubmit) {
        try {
          const buttonType = String(button?.getAttribute?.('type') || 'submit').toLowerCase();
          if (!button || buttonType === 'submit') form.requestSubmit(button || undefined);
          else form.requestSubmit();
          if (await waitForSubmissionAck(expected, baselineUserCount)) return;
        } catch (_) {}
      }

      if (newestUserMatches(expected, baselineUserCount)) return;

      const currentBox = composer();
      const currentButton = sendCandidatesForComposer(currentBox)[0] || button;
      if (currentButton && !disabled(currentButton)) {
        nativeMouseActivate(currentButton);
        if (await waitForSubmissionAck(expected, baselineUserCount)) return;
      }

      const retryBox = composer();
      if (retryBox && composerContainsPrompt(retryBox, expected) && !generating()) {
        dispatchEnter(retryBox);
        if (await waitForSubmissionAck(expected, baselineUserCount)) return;
      }

      if (attempt < SUBMISSION_ATTEMPTS) await sleep(DOM_POLL_MS + 50);
    }

    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
    throw new Error('PASI_NATIVE: prompt submission could not be verified after bounded attempts');
  }


  function completionMarkersSatisfied(responseText, markers) {
    const text = typeof responseText === 'string' ? responseText : '';
    if (!text.trim()) return false;
    const configured = Array.isArray(markers)
      ? markers.filter((marker) => typeof marker === 'string' && marker.trim()).map((marker) => marker.trim())
      : [];
    if (!configured.length) return true;
    const lines = text.split(/\r?\n/).map((line) => line.trim());
    return configured.some((marker) =>
      lines.some((line) => line === marker || line.startsWith(marker + ':'))
    );
  }

  async function waitForResponse(baseline, operationId, completionMarkers = []) {
    const started = Date.now();
    let sawGeneration = false;
    let stableFingerprint = '';
    let stableSince = 0;
    let lastOperationCheckAt = 0;
    while (Date.now() - started < TIMEOUTS.generation) {
      if (generating()) {
        sawGeneration = true;
        stableFingerprint = '';
        stableSince = 0;
      } else if (sawGeneration) {
        const response = latestAssistant();
        const current = fingerprint();
        if (response && current !== baseline) {
          if (current !== stableFingerprint) {
            stableFingerprint = current;
            stableSince = Date.now();
          }
          if (Date.now() - stableSince >= RESPONSE_SETTLE_MS && completionMarkersSatisfied(response, completionMarkers)) return response;
        }
      } else {
        const current = fingerprint();
        if (current !== baseline && current) {
          if (current !== stableFingerprint) {
            stableFingerprint = current;
            stableSince = Date.now();
          }
          const response = latestAssistant();
          if (Date.now() - stableSince >= RESPONSE_SETTLE_MS && /^PASI_RESULT_STATUS:\s*.+$/m.test(response)) return response;
        }
      }
      if (operationId && Date.now() - lastOperationCheckAt >= 2000) {
        lastOperationCheckAt = Date.now();
        try {
          const operationResponse = await bridge(`/operation?operation_id=${encodeURIComponent(operationId)}`);
          const current = operationResponse.ok ? operationResponse.json()?.operation : null;
          if (current?.status === 'cancelled') throw new Error('PASI_NATIVE: operation cancelled by runner');
          if (current?.status === 'failed') throw new Error(current.error || 'PASI_NATIVE: operation failed while generating');
        } catch (error) {
          if (String(error?.message || '').startsWith('PASI_NATIVE: operation ')) throw error;
        }
      }
      if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
      if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
      await sleep(DOM_POLL_MS * 2);
    }
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
      recovery_operation_id: operation.operation_id,
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
      recovery_operation_id: operation.operation_id,
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

  async function finishOperation(operationId, responseText = '', requireResponseText = false) {
    if (requireResponseText && (typeof responseText !== 'string' || !responseText.trim())) {
      throw new Error('PASI_NATIVE: response text unavailable; completion acknowledgement withheld');
    }
    const body = {
      operation_id: operationId,
      chat_url: chatUrl(),
      response_text: responseText.slice(0, 50000),
      response_text_available: typeof responseText === 'string' && Boolean(responseText.trim())
    };
    if (typeof responseText === 'string') Object.assign(body, completionProgress(responseText));
    // Completion acknowledgement is on the critical path to the next prompt.
    // Telemetry is intentionally fire-and-forget so a slow observation bridge
    // cannot add an avoidable network round trip between generations.
    void reportObservation('chatgpt_response', {
      chat_url: body.chat_url,
      response_text: body.response_text,
      response_text_available: body.response_text_available,
      ...(typeof responseText === 'string' ? completionProgress(responseText) : {}),
      conversation_context_exhausted: contextExhausted(),
      chat_exhausted: contextExhausted(),
      provider_usage_limited: usageLimited(),
      active_operation_id: operationId
    }).catch(() => {});

    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const response = await bridge('/chat/finished', { method: 'POST', body });
        if (response.ok) return;
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
        ) return;
      } catch (_) {}

      if (attempt < 3) await sleep(150);
    }
    throw lastError || new Error('PASI_NATIVE: bridge completion failed');
  }

  async function cancelOperation(operationId, reason) {
    try {
      const response = await bridge('/chat/cancel', {
        method: 'POST',
        body: { operation_id: operationId, reason: String(reason || 'cancelled by runner timeout') }
      });
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  async function failOperation(operationId, error, recoveryContext = null) {
    try {
      const body = {
        operation_id: operationId,
        error: String(error?.message || error)
      };
      if (recoveryContext && typeof recoveryContext === 'object') {
        body.recovery_context = recoveryContext;
      }
      const response = await bridge('/chat/failed', { method: 'POST', body });
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  async function processOperation(operation) {
    activeOperationId = operation.operation_id;
    processing = true;
    if (leaseTimerId !== null) clearInterval(leaseTimerId);
    leaseTimerId = setInterval(() => {
      controllerClaim().catch(() => {
        controllerLeader = false;
      });
    }, 3000);
    localStorage.setItem(ACTIVE_KEY, JSON.stringify({
      operation_id: operation.operation_id,
      operation_type: operation.operation_type,
      started_at: new Date().toISOString(),
      chat_url: chatUrl(),
      reasoning_mode: reasoningMode,
      github_attached: githubAttached,
      github_repository: githubRepository,
      recovery_context: recoveryContext()
    }));
    let finalized = false;
    try {
      switch (operation.operation_type) {
        case 'new_chat': await newChat(); break;
        case 'select_reasoning': await selectThinking(); break;
        case 'attach_github': await attachGithub(operation.prompt); break;
        case 'prompt': {
          await restoreRecoveryContext(operation.recovery_context);
          await selectThinking();
          if (reasoningMode !== 'unavailable') reasoningMode = 'thinking';

          const promptText = operationPrompt(operation);
          const activeState = readJsonStorage(ACTIVE_KEY) || {};
          const recoveryState = readJsonStorage(RECOVERY_KEY) || {};
          const savedBaseline = typeof activeState.baseline === 'string'
            ? activeState.baseline
            : (typeof recoveryState.baseline === 'string' ? recoveryState.baseline : '');

          if (userMessageExistsForOperation(operation.operation_id)) {
            if (typeof operation.response_text === 'string' && operation.response_text.trim()) {
              await finishOperation(operation.operation_id, operation.response_text, true);
              finalized = true;
              return;
            }
            if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
            const response = await waitForResponse(savedBaseline, operation.operation_id, operation.completion_markers || []);
            await finishOperation(operation.operation_id, response, true);
            finalized = true;
            return;
          }

          if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
          if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
          const box = await waitFor(composer, TIMEOUTS.composer);
          if (!box) throw new Error('PASI_NATIVE: composer unavailable');
          const baseline = fingerprint();
          localStorage.setItem(ACTIVE_KEY, JSON.stringify({ ...activeState, baseline }));
          setText(box, '');
          setText(box, promptText);
          // Scope the preflight check to the exact composer already being used.
          // A document-wide send lookup can bind to an unrelated control while the
          // bounded submitPrompt() path is still waiting for the real composer send action.
          const send = await waitForSend(box);
          if (!send) throw new Error('PASI_NATIVE: send control unavailable');
          await submitPrompt(promptText);
          const response = await waitForResponse(baseline, operation.operation_id, operation.completion_markers || []);
          await finishOperation(operation.operation_id, response, true);
          finalized = true;
          return;
        }
        default: throw new Error(`PASI_NATIVE: unsupported operation ${operation.operation_type}`);
      }
      await finishOperation(operation.operation_id);
      finalized = true;
    } catch (error) {
      const errorMessage = String(error?.message || error);
      const contextRetryCount = Number(operation.retry_counts?.context || 0);
      const contextRecoveryEligible =
        operation.operation_type === 'prompt' &&
        errorMessage.startsWith('CHAT_EXHAUSTED:') &&
        contextRetryCount < MAX_CONTEXT_AUTO_RECOVERIES;

      const responseRecoveryEligible =
        operation.operation_type === 'prompt' &&
        (
          errorMessage.startsWith('PASI_NATIVE: response text unavailable;') ||
          errorMessage.startsWith('PASI_NATIVE: ChatGPT generation timed out')
        );

      if (contextRecoveryEligible) {
        rememberContextRecovery(operation, error);
        await failOperation(
          operation.operation_id,
          error,
          recoveryContext()
        );
        finalized = false;
      } else if (responseRecoveryEligible) {
        rememberResponseRecovery(operation, error);
        await failOperation(
          operation.operation_id,
          error,
          recoveryContext()
        );
        finalized = false;
      } else {
        const failure = (
          errorMessage.startsWith('CHAT_EXHAUSTED:') &&
          contextRetryCount >= MAX_CONTEXT_AUTO_RECOVERIES
        )
          ? new Error('PASI_NATIVE: context recovery exhausted: ' + errorMessage)
          : error;
        finalized = await failOperation(operation.operation_id, failure);
      }
      throw error;
    } finally {
      activeOperationId = null;
      processing = false;
      if (leaseTimerId !== null) {
        clearInterval(leaseTimerId);
        leaseTimerId = null;
      }
      if (finalized) {
        localStorage.removeItem(ACTIVE_KEY);
        if (recoveryResumeOperationId() === operation.operation_id) {
          localStorage.removeItem(RECOVERY_KEY);
        }
      }
      // Do not wait for health telemetry or the normal 500 ms polling tick.
      // A completed operation can immediately claim the next queued prompt.
      void poll();
      void reportHealth();
    }
  }

  async function recoverInterruptedOperation() {
    try {
      if (!(await controllerClaim())) return;
      const stored = readJsonStorage(ACTIVE_KEY);
      const recovery = readJsonStorage(RECOVERY_KEY);
      const operationId = stored?.operation_id || recovery?.operation_id;
      if (!operationId) return;
      const current = await bridge(`/operation?operation_id=${encodeURIComponent(operationId)}`);
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
            await finishOperation(operationId, responseText, true);
          } catch (_) {
            // Keep the active marker so the next controller start can reconcile again.
            return;
          }
        } else if (!generating()) {
          const baseline = typeof stored?.baseline === 'string' ? stored.baseline : '';
          const visibleResponse = latestAssistant();
          const visibleFingerprint = fingerprint();
          if (visibleResponse && visibleFingerprint !== baseline) {
            try {
              await finishOperation(operationId, visibleResponse, true);
            } catch (_) {
              // Keep the active marker so recovery.js can retry against the same operation.
              return;
            }
          }
        }
        localStorage.removeItem(ACTIVE_KEY);
      } else if (operation.status === 'failed' || operation.status === 'cancelled') {
        localStorage.removeItem(ACTIVE_KEY);
        localStorage.removeItem(RECOVERY_KEY);
      } else if (operation.operation_type === 'prompt') {
        const baseline = typeof stored?.baseline === 'string'
          ? stored.baseline
          : (typeof recovery?.baseline === 'string' ? recovery.baseline : '');
        if (contextExhausted()) {
          await newChat();
          await failOperation(operationId, new Error('CHAT_EXHAUSTED: verified conversation context exhaustion; fresh chat prepared for retry.'));
          localStorage.removeItem(ACTIVE_KEY);
          localStorage.removeItem(RECOVERY_KEY);
          return;
        }
        if (userMessageExistsForOperation(operationId)) {
          const response = await waitForResponse(baseline, operationId);
          await finishOperation(operationId, response, true);
          localStorage.removeItem(ACTIVE_KEY);
          localStorage.removeItem(RECOVERY_KEY);
          return;
        }
        await failOperation(operationId, new Error('PASI_NATIVE: browser page reloaded during operation'));
        localStorage.removeItem(ACTIVE_KEY);
        localStorage.removeItem(RECOVERY_KEY);
      } else {
        await failOperation(operationId, new Error('PASI_NATIVE: browser page reloaded during operation'));
        localStorage.removeItem(ACTIVE_KEY);
        localStorage.removeItem(RECOVERY_KEY);
      }
      // content.js owns completion and retry mutation; recovery.js is observe-only.
    } catch (_) {}
  }

  function recoveryOperationId() {
    try {
      const state = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null');
      const value = state?.[RECOVERY_OPERATION_KEY] || state?.[RECOVERY_RESUME_OPERATION_KEY] || state?.operation_id;
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

  async function poll() {
    if (processing || activeOperationId !== null || extensionContextInvalidated) return;
    if (!(await controllerClaim())) return;
    try {
      const recoveryOperation = recoveryOperationId();
      if (localStorage.getItem(RECOVERY_KEY) && !recoveryOperation) return;

      const response = recoveryOperation
        ? await bridge('/chat/claim', {
            method: 'POST',
            body: { operation_id: recoveryOperation }
          })
        : await bridge('/next-operation', { method: 'POST', body: {} });
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
  }

  async function start() {
    await globalThis.PASI_TIMEOUT_POLICY?.load?.();
    await recoverInterruptedOperation();
    try { await reportHealth(); } catch (_) {}
    await poll();
    if (extensionContextInvalidated) return;
    pollTimerId = setInterval(poll, POLL_MS);
    healthTimerId = setInterval(reportHealth, HEALTH_MS);
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
