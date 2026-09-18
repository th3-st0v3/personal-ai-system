(() => {
  'use strict';

  const BRIDGE = 'http://127.0.0.1:8765';
  const CONTROLLER_VERSION = '2.4.10';
  const POLL_MS = 250;
  const HEALTH_MS = 5000;
  const DOM_POLL_MS = 100;
  const CLICK_SETTLE_MS = 250;
  const RESPONSE_SETTLE_MS = 200;
  const SUBMISSION_ACK_MS = 2500;
  const SUBMISSION_ATTEMPTS = 3;
  const TIMEOUTS = { menu: 8000, composer: 15000, send: 10000, submit: 5000, generation: 60 * 60 * 1000 };
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

  async function bridge(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeout || 10000);
    try {
      const response = await fetch(BRIDGE + path, {
        method: options.method || 'GET',
        headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
        credentials: 'omit'
      });
      const text = await response.text();
      return { ok: response.ok, status: response.status, text, json: () => JSON.parse(text) };
    } finally {
      clearTimeout(timer);
    }
  }

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && element.getClientRects().length > 0;
  }

  function disabled(element) {
    return Boolean(element) && (element.disabled === true || element.getAttribute('aria-disabled') === 'true');
  }

  function label(element) {
    return normalize([
      element?.getAttribute?.('aria-label'),
      element?.getAttribute?.('title'),
      element?.textContent
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
    if (isTextControl(element)) setNativeValue(element, value);
    else element.textContent = value;
    element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  }

  function insertText(element, text) { setText(element, text); }

  function readText(element) { return isTextControl(element) ? String(element.value || '') : String(element?.innerText || element?.textContent || ''); }

  function generating() {
    return Boolean(firstVisible(['button[data-testid="stop-button"]', 'button[aria-label="Stop generating"]', 'button[aria-label*="Stop"]']));
  }

  function chatUrl() { return /^https:\/\/chatgpt\.com\/c\//.test(location.href) ? location.href : null; }

  function contextExhausted() {
    const text = normalize(document.body?.innerText || '');
    return [
      'this conversation has reached its limit',
      'conversation has reached its limit',
      'conversation limit reached',
      'conversation is too long',
      'conversation is full',
      'maximum conversation length',
      'maximum length for this conversation',
      'context limit reached',
      'context window limit',
      'context length limit',
      'start a new chat to continue',
      'start a new conversation to continue'
    ].some((marker) => text.includes(marker));
  }

  function usageLimited() {
    if (contextExhausted()) return false;
    const text = normalize(document.body?.innerText || '');
    return [
      'current usage limit', 'usage limit reached', 'free tier limit', 'message limit',
      'daily limit', 'weekly limit', 'model usage limit', 'rate limit', 'too many requests'
    ].some((marker) => text.includes(marker));
  }

  function authRequired() {
    const text = normalize(document.body?.innerText || '');
    return ['log in to continue', 'sign in to continue', "verify you're human", 'security check', 'captcha', 'session has expired', 'cloudflare', 'turnstile'].some((marker) => text.includes(marker));
  }

  function thinkingEnabled() {
    const selected = document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], [data-state="on"], [data-state="active"]');
    for (const element of selected) {
      if (visible(element) && label(element).includes('thinking')) return true;
    }
    return null;
  }

  function userMessages() { return Array.from(document.querySelectorAll('[data-message-author-role="user"]')).filter(visible); }
  function assistantMessages() { return Array.from(document.querySelectorAll('[data-message-author-role="assistant"]')).filter(visible); }

  function messageText(node) {
    return String(node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
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

  async function selectThinking() {
    if (thinkingEnabled() === true) { reasoningMode = 'thinking'; return; }
    let control = findLabeled(['thinking', 'think', 'thinking mode'], ['button', '[role="button"]', '[role="option"]', '[role="menuitem"]']);
    if (!control) {
      const plus = await waitFor(() => firstVisible(['button[aria-label="Add files and more"]', 'button[aria-label*="Add files"]', 'button[aria-label*="Attach"]']), TIMEOUTS.menu);
      if (!plus || disabled(plus)) throw new Error('PASI_NATIVE: Thinking menu control unavailable');
      plus.click();
      control = await waitFor(() => findLabeled(['thinking', 'think', 'thinking mode'], ['button', '[role="button"]', '[role="option"]', '[role="menuitem"]']), TIMEOUTS.menu);
    }
    if (!control || disabled(control)) throw new Error('PASI_NATIVE: Thinking control unavailable');
    control.click();
    await sleep(CLICK_SETTLE_MS);
    if (thinkingEnabled() === false) throw new Error('PASI_NATIVE: Thinking state could not be verified');
    reasoningMode = 'thinking';
  }

  async function attachGithub(repository) {
    if (githubAttached) return;
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
    if (normalize(document.body?.innerText || '').includes('github needs to be connected')) throw new Error('PASI_NATIVE: GitHub connection unavailable');
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
      if (thinkingEnabled() !== true) await selectThinking();
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
      const text = String(markdown[i].innerText || markdown[i].textContent || '').replace(/\s+/g, ' ').trim();
      if (text) return text.slice(0, 50000);
    }
    return messageText(node).slice(0, 50000);
  }

  function latestAssistant() {
    const nodes = assistants();
    return nodes.length ? extractAssistant(nodes[nodes.length - 1]) : '';
  }

  function fingerprint() { return latestAssistant().slice(-4000); }

  async function waitForSend() {
    return waitFor(() => firstVisible(['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send message"]', 'button[type="submit"]'], true) || findLabeled(['send prompt', 'send message'], ['button', '[role="button"]'], true), TIMEOUTS.send);
  }

  async function waitForSubmissionAck(expected, baselineUserCount) {
    const started = Date.now();
    while (Date.now() - started < SUBMISSION_ACK_MS) {
      if (newestUserMatches(expected, baselineUserCount)) return true;
      if (generating() && userMessages().length > baselineUserCount) return true;
      await sleep(DOM_POLL_MS);
    }
    return false;
  }

  async function submitPrompt(expected) {
    const baselineUserCount = userMessages().length;
    for (let attempt = 1; attempt <= SUBMISSION_ATTEMPTS; attempt += 1) {
      const box = composer();
      if (!box) throw new Error('PASI_NATIVE: composer disappeared');
      if (!normalize(readText(box)).includes(normalize(expected))) throw new Error('PASI_NATIVE: composer lost the requested prompt before submission');

      const button = await waitForSend();
      if (button && !disabled(button)) {
        button.click();
      } else if (box.closest('form')?.requestSubmit) {
        box.closest('form').requestSubmit();
      } else {
        box.focus();
        box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
      }

      if (await waitForSubmissionAck(expected, baselineUserCount)) return;
      if (attempt < SUBMISSION_ATTEMPTS) await sleep(DOM_POLL_MS + 50);
    }
    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
    throw new Error('PASI_NATIVE: prompt submission could not be verified after bounded attempts');
  }

  async function waitForResponse(baseline) {
    const started = Date.now();
    let sawGeneration = false;
    while (Date.now() - started < TIMEOUTS.generation) {
      if (generating()) sawGeneration = true;
      else if (sawGeneration) {
        await sleep(RESPONSE_SETTLE_MS);
        const response = latestAssistant();
        if (response && fingerprint() !== baseline) return response;
      } else {
        const current = fingerprint();
        if (current !== baseline && current) return latestAssistant();
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
    await reportObservation('chatgpt_response', {
      chat_url: body.chat_url,
      response_text: body.response_text,
      response_text_available: body.response_text_available,
      conversation_context_exhausted: contextExhausted(),
      chat_exhausted: contextExhausted(),
      provider_usage_limited: usageLimited(),
      active_operation_id: operationId
    });

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
    localStorage.setItem(ACTIVE_KEY, JSON.stringify({
      operation_id: operation.operation_id,
      operation_type: operation.operation_type,
      started_at: new Date().toISOString(),
      chat_url: chatUrl(),
      reasoning_mode: reasoningMode,
      github_attached: githubAttached,
      github_repository: githubRepository
    }));
    let finalized = false;
    try {
      switch (operation.operation_type) {
        case 'new_chat': await newChat(); break;
        case 'select_reasoning': await selectThinking(); break;
        case 'attach_github': await attachGithub(operation.prompt); break;
        case 'prompt': {
          await restoreRecoveryContext(operation.recovery_context);
          if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
          if (usageLimited()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited');
          const box = await waitFor(composer, TIMEOUTS.composer);
          if (!box) throw new Error('PASI_NATIVE: composer unavailable');
          const baseline = fingerprint();
          let activeState = {};
          try {
            activeState = JSON.parse(localStorage.getItem(ACTIVE_KEY) || '{}');
          } catch (_) {}
          localStorage.setItem(ACTIVE_KEY, JSON.stringify({ ...activeState, baseline }));
          setText(box, '');
          insertText(box, operation.prompt);
          const send = await waitForSend();
          if (!send) throw new Error('PASI_NATIVE: send control unavailable');
          await submitPrompt(operation.prompt);
          const response = await waitForResponse(baseline);
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
        rememberContextRecovery(operation, error);
        finalized = false;
      } else if (responseRecoveryEligible) {
        rememberResponseRecovery(operation, error);
        finalized = false;
      } else {
        const failure = (
          errorMessage.startsWith('CHAT_EXHAUSTED:') &&
          Number(operation.retry_count || 0) >= MAX_CONTEXT_AUTO_RECOVERIES
        )
          ? new Error('PASI_NATIVE: context recovery exhausted: ' + errorMessage)
          : error;
        finalized = await failOperation(operation.operation_id, failure);
      }
      throw error;
    } finally {
      activeOperationId = null;
      processing = false;
      if (finalized) {
        localStorage.removeItem(ACTIVE_KEY);
        if (recoveryResumeOperationId() === operation.operation_id) {
          localStorage.removeItem(RECOVERY_KEY);
        }
      }
      await reportHealth();
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
          const baseline = typeof stored?.baseline === 'string' ? stored.baseline : '';
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

  async function poll() {
    if (processing || activeOperationId !== null) return;
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
      console.warn('[PASI native controller]', error);
      await reportHealth();
    }
  }

  async function start() {
    await recoverInterruptedOperation();
    try { await reportHealth(); } catch (_) {}
    await poll();
    setInterval(poll, POLL_MS);
    setInterval(reportHealth, HEALTH_MS);
  }

  start();
})();
