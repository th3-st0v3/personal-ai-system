// ==UserScript==
// @name         Personal AI System - ChatGPT Controller
// @namespace    http://tampermonkey.net/
// @version      2.4.6
// @description  Provider-specific ChatGPT browser controller for PASI.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    var BRIDGE_URL = 'http://127.0.0.1:8765';
    var CONTROLLER_VERSION = '2.4.6';
    var POLL_INTERVAL_MS = 250;
    var STATE_INTERVAL_MS = 5000;
    var DOM_POLL_INTERVAL_MS = 100;
    var COMPOSER_TIMEOUT_MS = 15000;
    var SEND_TIMEOUT_MS = 10000;
    var SUBMISSION_TIMEOUT_MS = 4000;
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
                        json: function () {
                            try { return Promise.resolve(JSON.parse(response.responseText)); }
                            catch (error) { return Promise.reject(error); }
                        }
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
            setInterval(reportChatState, STATE_INTERVAL_MS);
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
            activeOperationId = payload.operation.operation_id;
            processing = true;
            localStorage.setItem(ACTIVE_KEY, JSON.stringify({
                operation_id: activeOperationId,
                operation_type: payload.operation.operation_type,
                started_at: new Date().toISOString(),
                chat_url: chatUrl()
            }));
            try {
                await processOperation(payload.operation);
            } catch (error) {
                console.error('[PASI] Operation failed:', error);
                await reportFailure(activeOperationId, error);
            }
        } catch (error) {
            console.error('[PASI] Operation poll failed:', error);
        } finally {
            activeOperationId = null;
            processing = false;
        }
    }

    async function processOperation(operation) {
        if (!operation || typeof operation.operation_type !== 'string') throw new Error('ChatGPT operation type is missing.');
        var finalized = false;
        try {
            if (operation.operation_type === 'new_chat') {
                await startNewChat();
                githubAttached = false;
                reasoningMode = null;
                await reportFinished(operation.operation_id, false);
                finalized = true;
                await reportChatState(true);
                return;
            }
            if (operation.operation_type === 'select_reasoning') {
                await selectReasoningMode(operation.prompt);
                reasoningMode = normalize(operation.prompt) || 'thinking';
                await reportFinished(operation.operation_id, false);
                finalized = true;
                await reportChatState(true);
                return;
            }
            if (operation.operation_type === 'attach_github') {
                await attachGitHubContext(operation.prompt);
                githubAttached = true;
                await reportFinished(operation.operation_id, false);
                finalized = true;
                await reportChatState(true);
                return;
            }
            if (operation.operation_type === 'prompt') {
                await startPrompt(operation);
                finalized = true;
                return;
            }
            throw new Error('Unsupported ChatGPT operation type: ' + operation.operation_type);
        } catch (error) {
            var reported = await reportFailure(operation.operation_id, error);
            finalized = reported;
            throw error;
        } finally {
            if (finalized) localStorage.removeItem(ACTIVE_KEY);
            await reportChatState(true);
        }
    }

    async function startNewChat() {
        var previousLocation = window.location.href;
        var previousChat = chatUrl();
        var previousSignature = conversationSignature();
        var button = findNewChat();
        if (!button) {
            await sleep(DOM_POLL_INTERVAL_MS * 2);
            button = findNewChat();
        }
        if (!button) throw new Error('Could not find ChatGPT New chat control.');
        if (isDisabled(button)) throw new Error('ChatGPT New chat control is disabled.');
        button.click();

        var started = Date.now();
        while (Date.now() - started < NEW_CHAT_TIMEOUT_MS) {
            await sleep(DOM_POLL_INTERVAL_MS);
            var currentChat = chatUrl();
            var navigated = window.location.href !== previousLocation;
            var differentChat = Boolean(previousChat && currentChat && currentChat !== previousChat);
            var emptyConversation = userMessages().length === 0 && assistantMessages().length === 0 && findComposer() && !isGenerating();
            if (findComposer() && !isGenerating() && ((navigated && emptyConversation) || differentChat || (!previousChat && emptyConversation && conversationSignature() !== previousSignature))) {
                if (previousChat && currentChat && currentChat === previousChat) continue;
                githubAttached = false;
                reasoningMode = null;
                lastKnownChatUrl = currentChat;
                return;
            }
        }
        throw new Error('ChatGPT did not reach a verified new-chat state.');
    }

    function findNewChat() {
        var selectors = ['a[aria-label="New chat"]', 'button[aria-label="New chat"]', '[role="button"][aria-label="New chat"]', '[data-testid="new-chat-button"]'];
        var found = firstVisible(selectors);
        if (found) return found;
        return findVisibleLabeled('new chat', ['a', 'button', '[role="button"]']);
    }

    async function selectReasoningMode(mode) {
        mode = normalize(mode || 'thinking');
        if (mode !== 'thinking' && mode !== 'think') throw new Error('Unsupported ChatGPT reasoning mode: ' + mode);
        var direct = findReasoningControl();
        if (!direct) {
            var plus = await waitForPlusControl();
            if (!plus) throw new Error('Could not find ChatGPT plus control for Thinking mode.');
            plus.click();
            direct = await waitForReasoningControl();
        }
        if (!direct) throw new Error('ChatGPT Thinking control was not found.');
        if (isDisabled(direct)) throw new Error('ChatGPT Thinking control is disabled.');
        direct.click();
        await sleep(CLICK_SETTLE_MS);
        if (thinkingEnabled() === false) throw new Error('ChatGPT Thinking state could not be verified.');
    }

    function findReasoningControl() {
        return findVisibleLabeledAny(['thinking', 'think', 'thinking mode'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]', 'a']);
    }

    async function waitForReasoningControl() {
        var started = Date.now();
        while (Date.now() - started < MENU_TIMEOUT_MS) {
            var control = findReasoningControl();
            if (control) return control;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    async function attachGitHubContext(repository) {
        repository = String(repository || '').trim();
        if (!isRepositoryName(repository)) throw new Error('GitHub repository must be in owner/name form.');
        if (githubContextAlreadyAttached()) {
            githubAttached = true;
            return;
        }
        var plus = await waitForPlusControl();
        if (!plus) throw new Error('Could not find ChatGPT plus control for GitHub.');
        if (isDisabled(plus)) throw new Error('ChatGPT plus control is disabled.');
        plus.click();
        var github = await waitForGitHubControl();
        if (!github) throw new Error('GitHub app was not found in the ChatGPT menu.');
        if (isDisabled(github)) throw new Error('GitHub app control is disabled.');
        github.click();
        await sleep(CLICK_SETTLE_MS);
        var picker = await waitForRepositoryPicker();
        if (picker) await selectGitHubRepository(picker, repository);
        if (isGitHubConnectionFailureVisible()) throw new Error('GitHub repository access is unavailable.');
        githubAttached = true;
    }

    function githubContextAlreadyAttached() {
        if (githubAttached) return true;
        var composer = findComposer();
        if (!composer) return false;
        var form = composer.closest('form') || composer.parentElement;
        if (!form) return false;
        var text = normalize(form.innerText || form.textContent || '');
        if (text.indexOf('github') !== -1) return true;
        var githubNode = form.querySelector('[data-testid*="github" i], [aria-label*="github" i], [title*="github" i]');
        return Boolean(githubNode && isVisible(githubNode));
    }

    async function waitForPlusControl() {
        var started = Date.now();
        while (Date.now() - started < MENU_TIMEOUT_MS) {
            var control = findPlusControl();
            if (control) return control;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    function findPlusControl() {
        return firstVisible(['button[aria-label="Add files and more"]', 'button[aria-label*="Add files"]', 'button[aria-label*="Attach"]', 'button[title*="Add files"]', 'button[title*="Attach"]', '[role="button"][aria-label*="Add files"]', '[role="button"][aria-label*="Attach"]']) || findVisibleLabeledAny(['add files and more', 'add files', 'attach', 'more'], ['button', '[role="button"]']);
    }

    async function waitForGitHubControl() {
        var started = Date.now();
        while (Date.now() - started < MENU_TIMEOUT_MS) {
            var control = findGitHubControl();
            if (control) return control;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    function findGitHubControl() {
        return findVisibleLabeledAny(['github'], ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]', 'a']);
    }

    async function waitForRepositoryPicker() {
        var started = Date.now();
        while (Date.now() - started < MENU_TIMEOUT_MS) {
            var picker = findRepositoryPicker();
            if (picker) return picker;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    function findRepositoryPicker() {
        return firstVisible(['input[placeholder*="repository" i]', 'input[placeholder*="repo" i]', 'input[aria-label*="repository" i]', 'input[aria-label*="repo" i]', '[role="dialog"] input[type="text"]', '[role="dialog"] [role="textbox"]']);
    }

    async function selectGitHubRepository(picker, repository) {
        setTextControl(picker, repository);
        await sleep(CLICK_SETTLE_MS);
        var started = Date.now();
        while (Date.now() - started < MENU_TIMEOUT_MS) {
            var result = findRepositoryResult(repository);
            if (result) {
                result.click();
                await sleep(CLICK_SETTLE_MS);
                return;
            }
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        throw new Error('GitHub repository picker did not expose the requested repository.');
    }

    function findRepositoryResult(repository) {
        var needle = normalize(repository);
        var elements = document.querySelectorAll('[role="option"], [role="menuitem"], button, a, [role="button"]');
        for (var i = 0; i < elements.length; i += 1) {
            var element = elements[i];
            if (!isVisible(element)) continue;
            var label = normalize(getLabel(element));
            if (label === needle || label.indexOf(needle) !== -1) return element;
        }
        return null;
    }

    async function startPrompt(operation) {
        if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports that this conversation has reached its context or conversation-length limit.');
        if (isUsageLimitedVisible()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited.');
        var composer = await waitForComposer();
        if (!composer) throw new Error('Could not find ChatGPT composer.');
        var baseline = assistantFingerprint();
        clearComposer(composer);
        insertText(composer, operation.prompt);
        var send = await waitForSendButton();
        if (!send) throw new Error('Could not find ChatGPT send button.');
        await submitPrompt(operation.prompt);
        var response = await waitForAssistantResponse(baseline);
        if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports that this conversation has reached its context or conversation-length limit.');
        if (isUsageLimitedVisible()) throw new Error('CHAT_USAGE_LIMITED: ChatGPT provider usage is exhausted or rate limited.');
        if (!response) throw new Error('ChatGPT response could not be extracted from the page.');
        await reportResponseObservation(response);
        await reportFinished(operation.operation_id, true);
        console.log('[PASI] Operation completed with verified response:', operation.operation_id);
    }

    async function waitForComposer() {
        var started = Date.now();
        while (Date.now() - started < COMPOSER_TIMEOUT_MS) {
            var composer = findComposer();
            if (composer && !isGenerating()) return composer;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    function findComposer() {
        return firstVisible(['#prompt-textarea', 'textarea[data-id="root"]', 'textarea', '[contenteditable="true"][role="textbox"]', '[contenteditable="true"]']);
    }

    async function waitForSendButton() {
        var started = Date.now();
        while (Date.now() - started < SEND_TIMEOUT_MS) {
            var button = findSendButton();
            if (button) return button;
            await sleep(DOM_POLL_INTERVAL_MS);
        }
        return null;
    }

    function findSendButton() {
        return firstVisible(['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send message"]', 'button[type="submit"]'], true) || findVisibleLabeledAny(['send prompt', 'send message', 'send'], ['button', '[role="button"]'], true);
    }

    function userMessages() {
        return Array.prototype.filter.call(document.querySelectorAll('[data-message-author-role="user"]'), isVisible);
    }

    function assistantMessages() {
        return Array.prototype.filter.call(document.querySelectorAll('[data-message-author-role="assistant"]'), isVisible);
    }

    function messageText(node) {
        return String(node && (node.innerText || node.textContent) || '').replace(/\s+/g, ' ').trim();
    }

    function newestUserMatches(expected, baselineCount) {
        var nodes = userMessages();
        if (nodes.length <= baselineCount) return false;
        var needle = normalize(expected);
        for (var index = nodes.length - 1; index >= baselineCount; index -= 1) {
            var text = normalize(messageText(nodes[index]));
            if (text === needle || text.indexOf(needle) !== -1) return true;
        }
        return false;
    }

    function conversationSignature() {
        return userMessages().length + ':' + assistantMessages().length + ':' + assistantFingerprint();
    }

    async function submitPrompt(expected) {
        var baselineUserCount = userMessages().length;
        for (var attempt = 1; attempt <= SUBMISSION_ATTEMPTS; attempt += 1) {
            var composer = findComposer();
            if (!composer) throw new Error('Composer disappeared before submission.');
            if (normalize(readComposerText(composer)).indexOf(normalize(expected)) === -1) throw new Error('PASI: composer lost the requested prompt before submission.');
            var button = findSendButton();
            if (button && !isDisabled(button)) {
                console.log('[PASI] Submit attempt ' + attempt + ': clicking Send.');
                button.click();
            } else {
                var form = composer.closest('form');
                if (form && typeof form.requestSubmit === 'function') form.requestSubmit(button || undefined);
                else dispatchEnter(composer);
            }
            if (await waitForSubmissionAck(expected, baselineUserCount)) return;
            if (attempt < SUBMISSION_ATTEMPTS) await sleep(RETRY_DELAY_MS);
        }
        if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports that this conversation has reached its context or conversation-length limit.');
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

    async function waitForAssistantResponse(baseline) {
        var started = Date.now();
        var sawGeneration = false;
        while (Date.now() - started < GENERATION_TIMEOUT_MS) {
            var current = assistantFingerprint();
            if (isGenerating()) {
                sawGeneration = true;
            } else if (sawGeneration) {
                await sleep(RESPONSE_SETTLE_MS);
                var response = extractLatestAssistantResponse();
                if (response && assistantFingerprint() !== baseline) return response;
            } else if (current !== baseline) {
                var fast = extractLatestAssistantResponse();
                if (fast) return fast;
            }
            if (isConversationContextExhaustedVisible()) throw new Error('CHAT_EXHAUSTED: ChatGPT reports that this conversation has reached its context or conversation-length limit.');
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
            var markdownText = cleanLongText(markdown[i].innerText || markdown[i].textContent || '');
            if (markdownText) return markdownText;
        }
        return cleanLongText(node.innerText || node.textContent || '');
    }

    function assistantFingerprint() {
        var nodes = document.querySelectorAll('[data-message-author-role="assistant"]');
        if (!nodes.length) return '';
        var last = nodes[nodes.length - 1];
        return cleanLongText(last.innerText || last.textContent || '').slice(-4000);
    }

    function isConversationContextExhaustedVisible() {
        var text = normalize(document.body ? document.body.innerText : '');
        var markers = [
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
        ];
        for (var i = 0; i < markers.length; i += 1) {
            if (text.indexOf(markers[i]) !== -1) return true;
        }
        return false;
    }

    function isUsageLimitedVisible() {
        if (isConversationContextExhaustedVisible()) return false;
        var text = normalize(document.body ? document.body.innerText : '');
        var markers = [
            'current usage limit',
            'usage limit reached',
            'free tier limit',
            'message limit',
            'daily limit',
            'weekly limit',
            'model usage limit',
            'rate limit',
            'too many requests'
        ];
        for (var i = 0; i < markers.length; i += 1) {
            if (text.indexOf(markers[i]) !== -1) return true;
        }
        return false;
    }

    function isGitHubConnectionFailureVisible() {
        var text = normalize(document.body ? document.body.innerText : '');
        return text.indexOf('github needs to be connected') !== -1 || text.indexOf('connect github') !== -1 || text.indexOf('github is unavailable') !== -1 || text.indexOf('github connection failed') !== -1 || text.indexOf('no github repositories') !== -1;
    }

    async function reportResponseObservation(responseText) {
        await bridgeRequest('/browser/observation', {
            method: 'POST',
            body: { observation: {
                schema_version: 'chatgpt-controller-v2',
                captured_at: new Date().toISOString(),
                data: {
                    kind: 'chatgpt_response',
                    controller_version: CONTROLLER_VERSION,
                    chat_url: chatUrl(),
                    response_text: responseText.slice(0, 50000),
                    response_text_available: true,
                    conversation_context_exhausted: isConversationContextExhaustedVisible(),
                    chat_exhausted: isConversationContextExhaustedVisible(),
                    provider_usage_limited: isUsageLimitedVisible(),
                    active_operation_id: activeOperationId
                }
            } }
        });
    }

    async function reportChatState(force) {
        if (!force && (processing || activeOperationId !== null)) return;
        try {
            var currentUrl = chatUrl();
            if (currentUrl !== lastKnownChatUrl) {
                if (lastKnownChatUrl !== null || currentUrl !== null) {
                    await bridgeRequest('/browser/observation', {
                        method: 'POST',
                        body: { observation: {
                            schema_version: 'chatgpt-controller-chat-change-v1',
                            captured_at: new Date().toISOString(),
                            data: {
                                kind: 'chatgpt_chat_changed',
                                controller_version: CONTROLLER_VERSION,
                                previous_chat_url: lastKnownChatUrl,
                                new_chat_url: currentUrl,
                                active_operation_id: activeOperationId,
                                reason: processing ? 'during_operation' : 'navigation'
                            }
                        } }
                    });
                }
                if (!processing) {
                    githubAttached = false;
                    reasoningMode = null;
                }
                lastKnownChatUrl = currentUrl;
            }
            var exhausted = isConversationContextExhaustedVisible();
            var limited = isUsageLimitedVisible();
            await bridgeRequest('/browser/observation', {
                method: 'POST',
                body: { observation: {
                    schema_version: 'chatgpt-controller-state-v2',
                    captured_at: new Date().toISOString(),
                    data: {
                        kind: 'chatgpt_state',
                        controller_version: CONTROLLER_VERSION,
                        chat_url: currentUrl,
                        conversation_context_exhausted: exhausted,
                        chat_exhausted: exhausted,
                        provider_usage_limited: limited,
                        github_attached: githubAttached,
                        reasoning_mode: reasoningMode,
                        conversation_signature: conversationSignature(),
                        active_operation_id: activeOperationId
                    }
                } }
            });
        } catch (error) {
            console.warn('[PASI] Could not report ChatGPT state:', error);
        }
    }

    async function reportFinished(operationId, responseObserved) {
        var response = await bridgeRequest('/chat/finished', {
            method: 'POST',
            body: { operation_id: operationId, chat_url: chatUrl(), response_text_available: Boolean(responseObserved) }
        });
        if (!response.ok) throw new Error('Bridge completion failed: HTTP ' + response.status);
    }

    async function reportFailure(operationId, error) {
        try {
            var response = await bridgeRequest('/chat/failed', {
                method: 'POST',
                body: { operation_id: operationId, error: error instanceof Error ? error.message : String(error) }
            });
            return response.ok;
        } catch (reportError) {
            console.error('[PASI] Failed to report operation failure:', reportError);
            return false;
        }
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
        var form = composer.closest('form');
        if (form && typeof form.requestSubmit === 'function') {
            try { form.requestSubmit(findSendButton() || undefined); return true; } catch (error) { return false; }
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
        if (isTextControl(element)) {
            setNativeValue(element, value);
            element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            return;
        }
        element.textContent = value;
    }

    function setNativeValue(element, value) {
        var prototype = Object.getPrototypeOf(element);
        var descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
        if (descriptor && descriptor.set) descriptor.set.call(element, value);
        else element.value = value;
    }

    function findComposerContaining(expected) {
        var composer = findComposer();
        if (!composer) return null;
        return normalize(readComposerText(composer)).indexOf(normalize(expected)) !== -1 ? composer : null;
    }

    function readComposerText(element) {
        if (!element) return '';
        return isTextControl(element) ? String(element.value || '') : String(element.innerText || element.textContent || '');
    }

    function isTextControl(element) { return Boolean(element) && (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT'); }
    function isGenerating() { return Boolean(firstVisible(['button[data-testid="stop-button"]', 'button[aria-label="Stop generating"]', 'button[aria-label*="Stop"]'])); }
    function isRepositoryName(repository) { return /^[^/\s]+\/[^/\s]+$/.test(repository); }
    function isChatUrl(url) { return /^https:\/\/chatgpt\.com\/c\//.test(String(url || '')); }
    function chatUrl() { return isChatUrl(window.location.href) ? window.location.href : null; }

    function thinkingEnabled() {
        var selected = document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], [data-state="on"], [data-state="active"]');
        for (var i = 0; i < selected.length; i += 1) {
            if (isVisible(selected[i]) && getLabel(selected[i]).indexOf('thinking') !== -1) return true;
        }
        return null;
    }

    function firstVisible(selectors, requireEnabled) {
        for (var i = 0; i < selectors.length; i += 1) {
            var elements = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < elements.length; j += 1) {
                if (isVisible(elements[j]) && (!requireEnabled || !isDisabled(elements[j]))) return elements[j];
            }
        }
        return null;
    }

    function findVisibleLabeled(label, selectors) { return findVisibleLabeledAny([label], selectors, false); }

    function findVisibleLabeledAny(labels, selectors, requireEnabled) {
        var needles = labels.map(normalize);
        for (var i = 0; i < selectors.length; i += 1) {
            var elements = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < elements.length; j += 1) {
                var element = elements[j];
                if (!isVisible(element) || (requireEnabled && isDisabled(element))) continue;
                var label = normalize(getLabel(element));
                for (var k = 0; k < needles.length; k += 1) {
                    if (label === needles[k] || label.indexOf(needles[k] + ' ') === 0 || label.indexOf(' ' + needles[k]) !== -1) return element;
                }
            }
        }
        return null;
    }

    function getLabel(element) {
        if (!element) return '';
        var aria = element.getAttribute('aria-label');
        var title = element.getAttribute('title');
        var labelledBy = element.getAttribute('aria-labelledby');
        var labelledText = '';
        if (labelledBy) {
            labelledText = labelledBy.split(/\s+/).map(function (id) {
                var node = document.getElementById(id);
                return node ? (node.textContent || '') : '';
            }).join(' ');
        }
        return [aria, title, labelledText, element.textContent || ''].filter(Boolean).join(' ').trim();
    }

    function normalize(value) { return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
    function cleanLongText(value) { return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 50000); }
    function isVisible(element) {
        if (!element) return false;
        var style = window.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && element.getClientRects().length > 0;
    }
    function isDisabled(element) { return Boolean(element) && (element.disabled === true || element.getAttribute('disabled') !== null || element.getAttribute('aria-disabled') === 'true'); }
    function sleep(milliseconds) { return new Promise(function (resolve) { setTimeout(resolve, milliseconds); }); }
})();
