(() => {
  'use strict';

  const BRIDGE = 'http://127.0.0.1:8765';
  const POLL_MS = 1000;
  const HEALTH_MS = 5000;
  const TIMEOUTS = { menu: 8000, composer: 15000, send: 10000, submit: 5000, generation: 60 * 60 * 1000 };
  const ACTIVE_KEY = 'pasi:active-operation';
  let activeOperationId = null;
  let processing = false;
  let reasoningMode = null;
  let githubAttached = false;

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

  function insertText(element, text) {
    setText(element, text);
  }

  function readText(element) {
    return isTextControl(element) ? String(element.value || '') : String(element?.innerText || element?.textContent || '');
  }

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
    return !contextExhausted() && [
      'current usage limit', 'usage limit reached', 'free tier limit', 'message limit',
      'daily limit', 'weekly limit', 'model usage limit', 'rate limit', 'too many requests'
    ].some((marker) => normalize(document.body?.innerText || '').includes(marker));
  }

  function authRequired() {
    const text = normalize(document.body?.innerText || '');
    return [
      'log in to continue', 'sign in to continue', "verify you're human", 'security check',
      'captcha', 'session has expired'
    ].some((marker) => text.includes(marker));
  }

  function thinkingEnabled() {
    const selected = document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], [data-state="on"], [data-state="active"]');
    for (const element of selected) {
      if (visible(element) && label(element).includes('thinking')) return true;
    }
    return null;
  }

  async function reportObservation(kind, data) {
    try {
      await bridge('/browser/observation', {
        method: 'POST',
        body: { observation: { schema_version: 'pasi-native-chromium-v1', captured_at: new Date().toISOString(), data: { kind, ...data } } }
      });
    } catch (_) { /* browser should keep operating if bridge is briefly offline */ }
  }

  async function reportHealth() {
    await reportObservation('chatgpt_health', {
      chat_url: chatUrl(),
      provider_usage_limited: usageLimited(),
      auth_required: authRequired(),
      conversation_context_exhausted: contextExhausted(),
      thinking_enabled: thinkingEnabled(),
      page_visible: document.visibilityState !== 'hidden',
      composer_present: Boolean(composer()),
      native_controller: true
    });
    if (!processing && activeOperationId === null) {
      await reportObservation('chatgpt_state', {
        chat_url: chatUrl(),
        conversation_context_exhausted: contextExhausted(),
        chat_exhausted: contextExhausted(),
        github_attached: githubAttached,
        reasoning_mode: reasoningMode,
        native_controller: true
      });
    }
  }

  async function waitFor(select, timeout) {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      const value = select();
      if (value) return value;
      await sleep(200);
    }
    return null;
  }

  async function newChat() {
    const previous = location.href;
    const button = await waitFor(() => findLabeled(['new chat'], ['a', 'button', '[role="button"]']), TIMEOUTS.menu);
    if (!button || disabled(button)) throw new Error('PASI_NATIVE: New chat control unavailable');
    button.click();
    const ready = await waitFor(() => (location.href !== previous || chatUrl()) && composer() && !generating(), TIMEOUTS.menu + 7000);
    if (!ready) throw new Error('PASI_NATIVE: new chat did not reach a verified ready state');
    reasoningMode = null;
    githubAttached = false;
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
    await sleep(500);
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
    await sleep(500);
    if (normalize(document.body?.innerText || '').includes('github needs to be connected')) throw new Error('PASI_NATIVE: GitHub connection unavailable');
    githubAttached = true;
  }

  function assistants() {
    return Array.from(document.querySelectorAll('[data-message-author-role="assistant"]')).filter(visible);
  }

  function extractAssistant(node) {
    const markdown = Array.from(node.querySelectorAll?.('.markdown, [class*="markdown"]') || []).filter(visible);
    for (let i = markdown.length - 1; i >= 0; i -= 1) {
      const text = String(markdown[i].innerText || markdown[i].textContent || '').replace(/\s+/g, ' ').trim();
      if (text) return text.slice(0, 50000);
    }
    return String(node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 50000);
  }

  function latestAssistant() {
    const nodes = assistants();
    return nodes.length ? extractAssistant(nodes[nodes.length - 1]) : '';
  }

  function fingerprint() { return latestAssistant().slice(-4000); }

  async function waitForSend() {
    return waitFor(() => firstVisible(['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send message"]', 'button[type="submit"]'], true) || findLabeled(['send prompt', 'send message'], ['button', '[role="button"]'], true), TIMEOUTS.send);
  }

  async function submitPrompt(expected) {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      const box = composer();
      if (!box) throw new Error('PASI_NATIVE: composer disappeared');
      const button = await waitForSend();
      if (button && !disabled(button)) button.click();
      else if (box.closest('form')?.requestSubmit) box.closest('form').requestSubmit();
      if (await waitFor(() => generating() || !readText(composer()).includes(expected), TIMEOUTS.submit)) return;
      await sleep(300);
    }
    if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
    throw new Error('PASI_NATIVE: prompt submission could not be verified');
  }

  async function waitForResponse(baseline) {
    const started = Date.now();
    let sawGeneration = false;
    while (Date.now() - started < TIMEOUTS.generation) {
      if (generating()) sawGeneration = true;
      else if (sawGeneration) {
        await sleep(900);
        const response = latestAssistant();
        if (response && fingerprint() !== baseline) return response;
      } else {
        const current = fingerprint();
        if (current !== baseline && current) return latestAssistant();
      }
      if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
      await sleep(400);
    }
    throw new Error('PASI_NATIVE: ChatGPT generation timed out');
  }

  async function finishOperation(operationId, responseText = '') {
    await reportObservation('chatgpt_response', {
      chat_url: chatUrl(),
      response_text: responseText,
      response_text_available: Boolean(responseText),
      conversation_context_exhausted: contextExhausted(),
      chat_exhausted: contextExhausted(),
      active_operation_id: activeOperationId
    });
    const response = await bridge('/chat/finished', {
      method: 'POST',
      body: { operation_id: operationId, chat_url: location.href, response_text_available: Boolean(responseText) }
    });
    if (!response.ok) throw new Error('PASI_NATIVE: bridge completion failed');
  }

  async function failOperation(operationId, error) {
    try {
      await bridge('/chat/failed', { method: 'POST', body: { operation_id: operationId, error: String(error?.message || error) } });
    } catch (_) {}
  }

  async function processOperation(operation) {
    activeOperationId = operation.operation_id;
    processing = true;
    localStorage.setItem(ACTIVE_KEY, JSON.stringify({ operation_id: operation.operation_id, started_at: new Date().toISOString() }));
    try {
      switch (operation.operation_type) {
        case 'new_chat': await newChat(); break;
        case 'select_reasoning': await selectThinking(); break;
        case 'attach_github': await attachGithub(operation.prompt); break;
        case 'prompt': {
          if (contextExhausted()) throw new Error('CHAT_EXHAUSTED: conversation context is exhausted');
          const box = await waitFor(composer, TIMEOUTS.composer);
          if (!box) throw new Error('PASI_NATIVE: composer unavailable');
          const baseline = fingerprint();
          setText(box, '');
          insertText(box, operation.prompt);
          await waitForSend();
          await submitPrompt(operation.prompt);
          const response = await waitForResponse(baseline);
          await finishOperation(operation.operation_id, response);
          return;
        }
        default: throw new Error(`PASI_NATIVE: unsupported operation ${operation.operation_type}`);
      }
      await finishOperation(operation.operation_id);
    } catch (error) {
      await failOperation(operation.operation_id, error);
      throw error;
    } finally {
      activeOperationId = null;
      processing = false;
      localStorage.removeItem(ACTIVE_KEY);
      await reportHealth();
    }
  }

  async function recoverInterruptedOperation() {
    try {
      const stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      if (!stored?.operation_id) return;
      await failOperation(stored.operation_id, new Error('PASI_NATIVE: browser page reloaded during operation; operation returned to retry path'));
      localStorage.removeItem(ACTIVE_KEY);
    } catch (_) { localStorage.removeItem(ACTIVE_KEY); }
  }

  async function poll() {
    if (processing || activeOperationId !== null) return;
    try {
      const response = await bridge('/next-operation');
      if (!response.ok) return;
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
    setInterval(poll, POLL_MS);
    setInterval(reportHealth, HEALTH_MS);
  }

  start();
})();
