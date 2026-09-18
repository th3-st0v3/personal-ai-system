// ==UserScript==
// @name         Personal AI System - ChatGPT Controller
// @namespace    http://tampermonkey.net/
// @version      2.4.10
// @description  Provider-specific ChatGPT browser controller for PASI.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    var BRIDGE_URL = 'http://127.0.0.1:8765';
    var CONTROLLER_VERSION = '2.4.10';
    var POLL_INTERVAL_MS = 250;
    var STATE_INTERVAL_MS = 5000;
    var DOM_POLL_INTERVAL_MS = 100;
    var COMPOSER_TIMEOUT_MS = 15000;
    var SEND_TIMEOUT_MS = 10000;
    var SUBMISSION_ACK_MS = 2500;
    var SUBMISSION_ATTEMPTS = 3;
    var RETRY_DELAY_MS = 100;
    var CLICK_SETTLE_MS = 250;
    var RESPONSE_SETTLE_MS = 200;
    var GENERATION_TIMEOUT_MS = 60 * 60 * 1000;
    var NEW_CHAT_TIMEOUT_MS = 15000;
    var MENU_TIMEOUT_MS = 8000;
    var ACTIVE_KEY = 'pasi:active-operation';

    var activeOperationId = null;
    var processing = false;
    var githubAttached = false;
    var reasoningMode = null;
    var lastKnownChatUrl = null;

    window.__PASI_CHATGPT_ACTIVE_OPERATION__ = function () {
        return activeOperationId;
    };

    console.log('[PASI] ChatGPT Controller v' + CONTROLLER_VERSION + ' loaded.');
    start();

    function bridgeRequest(path, options) {
        options = options || {};
        return new Promise(function (resolve, reject) {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url: BRIDGE_URL + path,
                headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
                data: options.body ? JSON.stringify(options.body) : undefined,
                timeout: 10000,
                onload: function (response) {
                    resolve({
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        text: response.responseText,
                        json: function () { return JSON.parse(response.responseText); }
                    });
                },
                onerror: function () { reject(new Error('Bridge request failed: ' + path)); },
                ontimeout: function () { reject(new Error('Bridge request timed out: ' + path)); }
            });
        });
    }

    async function start() {
        try {
            await recoverInterruptedOperation();
            var health = await bridgeRequest('/health');
            if (!health.ok) return;
            await reportChatState(true);
            setInterval(pollForOperation, POLL_INTERVAL_MS);
            setInterval(function () { reportChatState(true); }, STATE_INTERVAL_MS);
        } catch (error) {
            console.error('[PASI] Controller startup failed:', error);
        }
    }

    async function pollForOperation() {
        if (processing || activeOperationId !== null) return;
        try {
            var response = await bridgeRequest('/next-operation');
            if (!response.ok) return;
            var payload = await response.json();
            if (!payload || !payload.operation) return;
            await processOperation(payload.operation);
        } catch (error) {
            console.error('[PASI] Operation poll failed:', error);
            await reportChatState(true);
        }
    }

    async function processOperation(operation) {
        if (!operation || typeof operation.operation_type !== 'string') throw new Error('ChatGPT operation type is missing.');
        activeOperationId = operation.operation_id;
        processing = true;
        localStorage.setItem(ACTIVE_KEY, JSON.stringify({
            operation_id: operation.operation_id,
            operation_type: operation.operation_type,
            started_at: new Date().toISOString(),
            chat_url: chatUrl()
        }));
        var finalized = false;
        try {
            if (operation.operation_type === 'new_chat') {
                await startNewChat();
                githubAttached = false;
                reasoningMode = null;
                await reportFinished(operation.operation_id, false);
            } else if (operation.operation_type === 'select_reasoning') {
                await selectReasoningMode(operation.prompt);
                reasoningMode = 'thinking';
                await reportFinished(operation.operation_id, false);
            } else if (operation.operation_type === 'attach_github') {
                await attachGitHubContext(operation.prompt);
                githubAttached = true;
                await reportFinished(operation.operation_id, false);
            } else if (operation.operation_type === 'prompt') {
                await startPrompt(operation);
                finalized = true;
                return;
            } else {
                throw new Error('Unsupported ChatGPT operation type: ' + operation.operation_type);
            }
            finalized = true;
        } catch (error) {
            finalized = await reportFailure(operation.operation_id, error);
            throw error;
        } finally {
            if (finalized) localStorage.removeItem(ACTIVE_KEY);
            activeOperationId = null;
            processing = false;
            await reportChatState(true);
        }
    }

    async function startNewChat() {
        var previousLocation = window.location.href;
        var previousChat = chatUrl();
        var previousSignature = conversationSignature();
        var button = await waitFor(function () { return findNewChat(); }, NEW_CHAT_TIMEOUT_MS);
        if (!button) throw new Error('Could not find ChatGPT New chat control.');
        if (isDisabled(button)) throw new Error('ChatGPT New chat control is disabled.');
        button.click();

        var started = Date.now();
        while (Date.now() - started < NEW_CHAT_TIMEOUT_MS) {
            await sleep(DOM_POLL_INTERVAL_MS);
            var currentChat = chatUrl();
            var navigated = window.location.href !== previousLocation;
            var differentChat = Boolean(previousChat && currentChat && currentChat !== previousChat);
            var initialChatReady = !previousChat && navigated && currentChat && findComposer() && !isGenerating() && userMessages().length === 0 && assistantMessages().length === 0 && conversationSignature() !== previousSignature;
            if (findComposer() && !isGenerating() && (differentChat || initialChatReady)) {
                if (previousChat && (!currentChat || currentChat === previousChat)) continue;
                githubAttached = false;
                reasoningMode = null;
                lastKnownChatUrl = currentChat;
                return;
            }
        }
        throw new Error('ChatGPT did not reach a verified new-chat state.');
    }

    function findNewChat() {
        return firstVisible(['a[aria-label="New chat"]', 'button[aria-label="New chat"]', '[role="button"][aria-label="New chat"]', '[data-testid="new-chat-button"]']) || findVisibleLabeledAny(['new chat'], ['a', 'button', '[role="button"]']);
    }

    async function selectReasoningMode(mode) {
        mode = normalize(mode || 'thinking');
        if (mode !== 'thinking' && mode !== 'think') throw new Error('Unsupported ChatGPT reasoning mode: ' + mode);
        var control = findReasoningControl();
        if (!control) {
            var plus = await waitForPlusControl();
            if (!plus) throw new Error('Could not find ChatGPT plus control for Thinking mode.');
            plus.click();
            control = await waitForReasoningControl();
        }
        if (!control) throw new Error('ChatGPT Thinking control was not found.');
        if (isDisabled(control)) throw new Error('ChatGPT Thinking control is disabled.');
        control.click();
        await sleep(CLICK_SETTLE_MS);
        if (thinkingEnabled() === false) throw new Error('ChatGPT Thinking state could not be verified.');
    }

    function findReasoningControl() { return findVisibleLabeledAny(['thinking', 'think', 'thinking mode'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]', 'a']); }

    async function waitForReasoningControl() { return waitFor(findReasoningControl, MENU_TIMEOUT_MS); }

    async function attachGitHubContext(repository) {
        repository = String(repository || '').trim();
        if (!isRepositoryName(repository)) throw new Error('GitHub repository must be in owner/name form.');
        if (githubContextAlreadyAttached()) { githubAttached = true; return; }
        var plus = await waitForPlusControl();
        if (!plus) throw new Error('Could not find ChatGPT plus control for GitHub.');
        if (isDisabled(plus)) throw new Error('ChatGPT plus control is disabled.');
        plus.click();
        var github = await waitForGitHubControl();
        if (!github) throw new Error('GitHub app was not found in the ChatGPT menu.');
        github.click();
        await sleep(CLICK_SETTLE_MS);
        var picker = await waitForRepositoryPicker();
        if (!picker) throw new Error('GitHub repository picker was not found.');
        await selectGitHubRepository(picker, repository);
        if (isGitHubConnectionFailureVisible()) throw new Error('GitHub repository access is unavailable.');
        githubAttached = true;
    }

    function githubContextAlreadyAttached() {
        if (githubAttached) return true;
        var composer = findComposer();
        if (!composer) return false;
        var container = composer.closest('form') || composer.parentElement;
        if (!container) return false;
        var text = normalize(container.innerText || container.textContent || '');
        return text.indexOf('github') !== -1;
    }

    async function waitForPlusControl() { return waitFor(findPlusControl, MENU_TIMEOUT_MS); }
    function findPlusControl() { return firstVisible(['button[aria-label="Add files and more"]', 'button[aria-label*="Add files"]', 'button[aria-label*="Attach"]', '[role="button"][aria-label*="Add files"]', '[role="button"][aria-label*="Attach"]']) || findVisibleLabeledAny(['add files and more', 'add files', 'attach', 'more'], ['button', '[role="button"]']); }
    async function waitForGitHubControl() { return waitFor(findGitHubControl, MENU_TIMEOUT_MS); }
    function findGitHubControl() { return findVisibleLabeledAny(['github'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]', 'a']); }
    async function waitForRepositoryPicker() { return waitFor(findRepositoryPicker, MENU_TIMEOUT_MS); }
    function findRepositoryPicker() { return firstVisible(['input[placeholder*="repository" i]', 'input[placeholder*="repo" i]', 'input[aria-label*="repository" i]', 'input[aria-label*="repo" i]', '[role="dialog"] input[type="text"]', '[role="dialog"] [role="textbox"]']); }

    async function selectGitHubRepository(picker, repository) {
        setTextControl(picker, repository);
        await sleep(CLICK_SETTLE_MS);
        var result = await waitFor(function () { return findRepositoryResult(repository); }, MENU_TIMEOUT_MS);
        if (!result) throw new Error('GitHub repository picker did not expose the requested repository.');
        result.click();
        await sleep(CLICK_SETTLE_MS);
    }

    function findRepositoryResult(repository) {
        var needle = normalize(repository);
        var elements = document.querySelectorAll('[role="option"], [role="menuitem"], button, a, [role="button"]');
        for (var i = 0; i < elements.length; i += 1) {
            if (!isVisible(elements[i])) continue;
            var text = normalize(getLabel(elements[i]));
            if (text === needle || text.indexOf(needle) !== -1) return elements[i];
        }
        return null;
    }

    async function startPrompt(operation) {
        await selectReasoningMode('thinking');
        reasoningMode = 'thinking';
        if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports conversation/context exhaustion.');
        if (isUsageLimitedVisible()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited.');
        var composer = await waitForComposer();
        if (!composer) throw new Error('Could not find ChatGPT composer.');
        var baseline = assistantFingerprint();
        var baselineUsers = userMessages().length;
        clearComposer(composer);
        insertText(composer, operation.prompt);
        var send = await waitForSendButton();
        if (!send) throw new Error('Could not find ChatGPT send button.');
        await submitPrompt(operation.prompt, baselineUsers);
        var response = await waitForAssistantResponse(baseline);
        if (!response) throw new Error('ChatGPT response could not be extracted from the page.');
        await reportResponseObservation(response);
        await reportFinished(operation.operation_id, response);
    }

    async function waitForComposer() { return waitFor(function () { var c = findComposer(); return c && !isGenerating() ? c : null; }, COMPOSER_TIMEOUT_MS); }
    function findComposer() { return firstVisible(['#prompt-textarea', 'textarea[data-id="root"]', 'textarea', '[contenteditable="true"][role="textbox"]', '[contenteditable="true"]']); }
    async function waitForSendButton() { return waitFor(findSendButton, SEND_TIMEOUT_MS); }
    function findSendButton() { return firstVisible(['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send message"]', 'button[type="submit"]'], true) || findVisibleLabeledAny(['send prompt', 'send message', 'send'], ['button', '[role="button"]'], true); }

    async function submitPrompt(expected, baselineUserCount) {
        for (var attempt = 1; attempt <= SUBMISSION_ATTEMPTS; attempt += 1) {
            var composer = findComposer();
            if (!composer) throw new Error('Composer disappeared before submission.');
            if (normalize(readComposerText(composer)).indexOf(normalize(expected)) === -1) throw new Error('PASI: composer lost the requested prompt before submission.');
            var button = findSendButton();
            if (button && !isDisabled(button)) button.click();
            else if (!requestFormSubmit(composer)) dispatchEnter(composer);
            if (await waitForSubmissionAck(expected, baselineUserCount)) return;
            if (attempt < SUBMISSION_ATTEMPTS) await sleep(RETRY_DELAY_MS);
        }
        if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports conversation/context exhaustion.');
        if (isUsageLimitedVisible()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited.');
        throw new Error('PASI: prompt submission could not be verified after bounded attempts.');
    }

    async function waitForSubmissionAck(expected, baselineUserCount) {
        var started = Date.now();
        while (Date.now() - started < SUBMISSION_ACK_MS) {
            if (newestUserMatches(expected, baselineUserCount)) return true;
            if (isGenerating() && userMessages().length > baselineUserCount) return true;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return false;
    }

    function userMessages() { return Array.prototype.filter.call(document.querySelectorAll('[data-message-author-role="user"]'), isVisible); }
    function assistantMessages() { return Array.prototype.filter.call(document.querySelectorAll('[data-message-author-role="assistant"]'), isVisible); }
    function newestUserMatches(expected, baselineUserCount) {
        var nodes = userMessages();
        if (nodes.length <= baselineUserCount) return false;
        var needle = normalize(expected);
        for (var i = nodes.length - 1; i >= baselineUserCount; i -= 1) {
            var text = normalize(messageText(nodes[i]));
            if (text === needle || text.indexOf(needle) !== -1) return true;
        }
        return false;
    }
    function conversationSignature() { return userMessages().length + ':' + assistantMessages().length + ':' + assistantFingerprint(); }
    function messageText(node) { return String(node && (node.innerText || node.textContent) || '').replace(/\s+/g, ' ').trim(); }
    function assistantFingerprint() { var nodes = assistantMessages(); return nodes.length ? cleanLongText(nodes[nodes.length - 1].innerText || nodes[nodes.length - 1].textContent || '').slice(-4000) : ''; }
    function cleanLongText(value) { return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 50000); }

    async function waitForAssistantResponse(baseline) {
        var started = Date.now();
        var sawGeneration = false;
        while (Date.now() - started < GENERATION_TIMEOUT_MS) {
            if (isGenerating()) sawGeneration = true;
            else if (sawGeneration) {
                await sleep(RESPONSE_SETTLE_MS);
                var response = extractLatestAssistantResponse();
                if (response && assistantFingerprint() !== baseline) return response;
            } else if (assistantFingerprint() !== baseline) {
                var fast = extractLatestAssistantResponse();
                if (fast) return fast;
            }
            if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports conversation/context exhaustion.');
            if (isUsageLimitedVisible()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited.');
            await sleep(DOM_POLL_INTERVAL_MS * 2);
        }
        throw new Error('ChatGPT generation timed out.');
    }

    function extractLatestAssistantResponse() {
        var nodes = document.querySelectorAll('[data-message-author-role="assistant"]');
        for (var i = nodes.length - 1; i >= 0; i -= 1) {
            if (!isVisible(nodes[i])) continue;
            var text = extractAssistantNodeText(nodes[i]);
            if (text) return text;
        }
        return '';
    }
    function extractAssistantNodeText(node) {
        var markdown = node.querySelectorAll ? node.querySelectorAll('.markdown, [class*="markdown"]') : [];
        for (var i = markdown.length - 1; i >= 0; i -= 1) {
            if (!isVisible(markdown[i])) continue;
            var text = cleanLongText(markdown[i].innerText || markdown[i].textContent || '');
            if (text) return text;
        }
        return cleanLongText(node.innerText || node.textContent || '');
    }

    function isConversationContextExhaustedVisible() {
        var text = normalize(document.body ? document.body.innerText : '');
        var markers = ['this conversation has reached its limit', 'conversation has reached its limit', 'conversation limit reached', 'conversation is too long', 'conversation is full', 'maximum conversation length', 'maximum length for this conversation', 'context limit reached', 'context window limit', 'context length limit', 'start a new chat to continue', 'start a new conversation to continue'];
        for (var i = 0; i < markers.length; i += 1) if (text.indexOf(markers[i]) !== -1) return true;
        return false;
    }
    function isUsageLimitedVisible() {
        if (isConversationContextExhaustedVisible()) return false;
        var text = normalize(document.body ? document.body.innerText : '');
        var markers = ['current usage limit', 'usage limit reached', 'free tier limit', 'message limit', 'daily limit', 'weekly limit', 'model usage limit', 'rate limit', 'too many requests'];
        for (var i = 0; i < markers.length; i += 1) if (text.indexOf(markers[i]) !== -1) return true;
        return false;
    }

    async function reportResponseObservation(responseText) {
        try {
            await bridgeRequest('/browser/observation', { method: 'POST', body: { observation: {
                schema_version: 'chatgpt-controller-v2',
                captured_at: new Date().toISOString(),
                data: { kind: 'chatgpt_response', controller_version: CONTROLLER_VERSION, chat_url: chatUrl(), response_text: responseText.slice(0, 50000), response_text_available: true, conversation_context_exhausted: isConversationContextExhaustedVisible(), chat_exhausted: isConversationContextExhaustedVisible(), provider_usage_limited: isUsageLimitedVisible(), active_operation_id: activeOperationId }
            } } });
        } catch (error) {
            console.warn('[PASI] Could not persist ChatGPT response observation; completion path remains authoritative.', error);
        }
    }

    async function reportChatState(force) {
        try {
            var currentUrl = chatUrl();
            if (currentUrl !== lastKnownChatUrl) {
                if (lastKnownChatUrl !== null || currentUrl !== null) {
                    await bridgeRequest('/browser/observation', { method: 'POST', body: { observation: {
                        schema_version: 'chatgpt-controller-chat-change-v1',
                        captured_at: new Date().toISOString(),
                        data: { kind: 'chatgpt_chat_changed', controller_version: CONTROLLER_VERSION, previous_chat_url: lastKnownChatUrl, new_chat_url: currentUrl, active_operation_id: activeOperationId, reason: processing ? 'during_operation' : 'navigation' }
                    } } });
                }
                if (!processing) { githubAttached = false; reasoningMode = null; }
                lastKnownChatUrl = currentUrl;
            }
            var exhausted = isConversationContextExhaustedVisible();
            var limited = isUsageLimitedVisible();
            await bridgeRequest('/browser/observation', { method: 'POST', body: { observation: {
                schema_version: 'chatgpt-controller-state-v2',
                captured_at: new Date().toISOString(),
                data: { kind: 'chatgpt_state', controller_version: CONTROLLER_VERSION, chat_url: currentUrl, conversation_context_exhausted: exhausted, chat_exhausted: exhausted, provider_usage_limited: limited, github_attached: githubAttached, reasoning_mode: reasoningMode, conversation_signature: conversationSignature(), active_operation_id: activeOperationId }
            } } });
        } catch (error) { console.warn('[PASI] Could not report ChatGPT state:', error); }
    }

    async function reportFinished(operationId, responseText) {
        var body = { operation_id: operationId, chat_url: chatUrl(), response_text_available: typeof responseText === 'string' && Boolean(responseText.trim()) };
        if (typeof responseText === 'string') body.response_text = responseText.slice(0, 50000);
        var lastError = null;
        for (var attempt = 1; attempt <= 3; attempt += 1) {
            try {
                var response = await bridgeRequest('/chat/finished', { method: 'POST', body: body });
                if (response.ok) return;
                lastError = new Error('Bridge completion failed: HTTP ' + response.status);
            } catch (error) {
                lastError = error;
            }
            try {
                var current = await bridgeRequest('/operation?operation_id=' + encodeURIComponent(operationId));
                if (current.ok) {
                    var payload = await current.json();
                    if (payload && payload.operation && payload.operation.status === 'completed' && payload.operation.response_text_available === true && typeof payload.operation.response_text === 'string' && Boolean(payload.operation.response_text.trim())) return;
                }
            } catch (_) {}
            if (attempt < 3) await sleep(150);
        }
        throw lastError || new Error('Bridge completion failed.');
    }

    async function reportFailure(operationId, error) {
        try {
            var response = await bridgeRequest('/chat/failed', { method: 'POST', body: { operation_id: operationId, error: error instanceof Error ? error.message : String(error) } });
            return response.ok;
        } catch (_) { return false; }
    }

    async function recoverInterruptedOperation() {
        try {
            var stored = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
            if (!stored || !stored.operation_id) return;
            var ok = await reportFailure(stored.operation_id, new Error('PASI: browser page reloaded during operation; current chat preserved for bounded retry'));
            if (ok) localStorage.removeItem(ACTIVE_KEY);
        } catch (_) {}
    }

    function requestFormSubmit(composer) {
        var form = composer && composer.closest('form');
        if (form && typeof form.requestSubmit === 'function') {
            try { form.requestSubmit(findSendButton() || undefined); return true; } catch (_) {}
        }
        return false;
    }

    function dispatchEnter(element) {
        element.focus();
        var init = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
        element.dispatchEvent(new KeyboardEvent('keydown', init));
        element.dispatchEvent(new KeyboardEvent('keypress', init));
        element.dispatchEvent(new KeyboardEvent('keyup', init));
    }

    function clearComposer(element) { element.focus(); setTextControl(element, ''); }
    function insertText(element, text) {
        element.focus();
        if (isTextControl(element)) {
            setNativeValue(element, text);
            element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
            return;
        }
        var selection = window.getSelection();
        if (selection) {
            selection.removeAllRanges();
            var range = document.createRange();
            range.selectNodeContents(element);
            range.collapse(false);
            selection.addRange(range);
        }
        if (!document.execCommand('insertText', false, text)) element.textContent = text;
        element.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'insertText', data: text }));
    }
    function setTextControl(element, value) {
        if (isTextControl(element)) { setNativeValue(element, value); element.dispatchEvent(new Event('input', { bubbles: true, composed: true })); return; }
        element.textContent = value;
    }
    function setNativeValue(element, value) {
        var prototype = Object.getPrototypeOf(element);
        var descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
        if (descriptor && descriptor.set) descriptor.set.call(element, value); else element.value = value;
    }

    function waitFor(select, timeout) {
        var started = Date.now();
        return new Promise(function (resolve) {
            function probe() {
                var value = select();
                if (value) { resolve(value); return; }
                if (Date.now() - started >= timeout) { resolve(null); return; }
                setTimeout(probe, DOM_POLL_INTERVAL_MS);
            }
            probe();
        });
    }

    function getLabel(element) {
        if (!element) return '';
        return [element.getAttribute('aria-label'), element.getAttribute('title'), element.textContent || ''].filter(Boolean).join(' ');
    }
    function normalize(value) { return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
    function isVisible(element) {
        if (!element) return false;
        var style = window.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && element.getClientRects().length > 0;
    }
    function isDisabled(element) { return Boolean(element) && (element.disabled === true || element.getAttribute('disabled') !== null || element.getAttribute('aria-disabled') === 'true'); }
    function isTextControl(element) { return Boolean(element) && (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT'); }
    function isGenerating() { return Boolean(firstVisible(['button[data-testid="stop-button"]', 'button[aria-label="Stop generating"]', 'button[aria-label*="Stop"]'])); }
    function isRepositoryName(repository) { return /^[^/\s]+\/[^/\s]+$/.test(repository); }
    function isChatUrl(url) { return /^https:\/\/chatgpt\.com\/c\//.test(String(url || '')); }
    function chatUrl() { return isChatUrl(window.location.href) ? window.location.href : null; }
    function thinkingEnabled() {
        var selected = document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], [data-state="on"], [data-state="active"]');
        for (var i = 0; i < selected.length; i += 1) if (isVisible(selected[i]) && normalize(getLabel(selected[i])).indexOf('thinking') !== -1) return true;
        return null;
    }
    function firstVisible(selectors, requireEnabled) {
        for (var i = 0; i < selectors.length; i += 1) {
            var elements = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < elements.length; j += 1) if (isVisible(elements[j]) && (!requireEnabled || !isDisabled(elements[j]))) return elements[j];
        }
        return null;
    }
    function findVisibleLabeledAny(labels, selectors, requireEnabled) {
        var needles = labels.map(normalize);
        for (var i = 0; i < selectors.length; i += 1) {
            var elements = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < elements.length; j += 1) {
                var element = elements[j];
                if (!isVisible(element) || (requireEnabled && isDisabled(element))) continue;
                var label = normalize(getLabel(element));
                for (var k = 0; k < needles.length; k += 1) if (label === needles[k] || label.indexOf(needles[k] + ' ') === 0 || label.indexOf(' ' + needles[k]) !== -1) return element;
            }
        }
        return null;
    }
    function sleep(milliseconds) { return new Promise(function (resolve) { setTimeout(resolve, milliseconds); }); }
    function readComposerText(element) { return isTextControl(element) ? String(element.value || '') : String(element && (element.innerText || element.textContent) || ''); }

})();