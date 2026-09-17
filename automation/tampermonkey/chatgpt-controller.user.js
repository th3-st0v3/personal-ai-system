// ==UserScript==
// @name         Personal AI System - ChatGPT Controller
// @namespace    http://tampermonkey.net/
// @version      2.2.0
// @description  Connects ChatGPT to the local Personal AI System orchestrator.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    var BRIDGE_URL = 'http://127.0.0.1:8765';
    var POLL_INTERVAL_MS = 1000;
    var COMPOSER_TIMEOUT_MS = 15000;
    var PROMPT_VERIFY_TIMEOUT_MS = 5000;
    var SEND_BUTTON_TIMEOUT_MS = 10000;
    var SUBMISSION_TIMEOUT_MS = 3000;
    var SUBMISSION_RETRY_DELAY_MS = 350;
    var NEW_CHAT_TIMEOUT_MS = 15000;
    var GENERATION_POLL_MS = 500;
    var GENERATION_TIMEOUT_MS = 60 * 60 * 1000;

    var activeOperationId = null;
    var processing = false;

    console.log('[PASI] ChatGPT Controller v2.2.0 loaded.');
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
                        json: function () { return Promise.resolve(JSON.parse(response.responseText)); }
                    });
                },
                onerror: function () { reject(new Error('Bridge request failed: ' + path)); },
                ontimeout: function () { reject(new Error('Bridge request timed out: ' + path)); }
            });
        });
    }

    async function start() {
        try {
            var health = await bridgeRequest('/health');
            if (!health.ok) {
                console.warn('[PASI] Local bridge is unavailable.');
                return;
            }
            console.log('[PASI] Local bridge connected.');
            console.log('[PASI] Starting bridge polling.');
            setInterval(pollForOperation, POLL_INTERVAL_MS);
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
            console.log('[PASI] Claimed operation:', payload.operation);
            await processOperation(payload.operation);
        } catch (error) {
            console.error('[PASI] Operation failed:', error);
            if (activeOperationId !== null) await reportFailure(activeOperationId, error);
        } finally {
            activeOperationId = null;
            processing = false;
        }
    }

    async function processOperation(operation) {
        if (!operation || typeof operation.operation_type !== 'string') {
            throw new Error('ChatGPT operation type is missing.');
        }
        if (operation.operation_type === 'new_chat') {
            await startNewChat();
            await reportFinished(operation.operation_id, false);
            console.log('[PASI] New ChatGPT conversation started.');
            return;
        }
        if (operation.operation_type === 'select_reasoning') {
            throw new Error('ChatGPT reasoning-mode control is not available in this controller yet.');
        }
        if (operation.operation_type !== 'prompt') {
            throw new Error('Unsupported ChatGPT operation type: ' + operation.operation_type);
        }
        await startPrompt(operation);
    }

    async function startNewChat() {
        var previousUrl = window.location.href;
        var button = findNewChat();
        if (!button) {
            await sleep(500);
            button = findNewChat();
        }
        if (!button) {
            throw new Error('Could not find ChatGPT New chat control. ' + newChatDiagnostics());
        }
        if (isDisabled(button)) {
            throw new Error('ChatGPT New chat control is disabled.');
        }
        console.log('[PASI] Clicking New chat:', getLabel(button));
        button.click();
        var startTime = Date.now();
        while (Date.now() - startTime < NEW_CHAT_TIMEOUT_MS) {
            await sleep(250);
            if (isNewChatReady(previousUrl)) {
                console.log('[PASI] New ChatGPT conversation ready:', window.location.href);
                return;
            }
        }
        throw new Error('ChatGPT did not reach a verified new-chat state.');
    }

    function findNewChat() {
        var selectors = [
            'a[aria-label="New chat"]',
            'button[aria-label="New chat"]',
            '[role="button"][aria-label="New chat"]',
            '[data-testid="new-chat-button"]'
        ];
        var i;
        var j;
        var elements;
        var element;
        for (i = 0; i < selectors.length; i += 1) {
            elements = document.querySelectorAll(selectors[i]);
            for (j = 0; j < elements.length; j += 1) {
                element = elements[j];
                if (isVisible(element)) return element;
            }
        }
        elements = document.querySelectorAll('a, button, [role="button"]');
        for (i = 0; i < elements.length; i += 1) {
            element = elements[i];
            if (!isVisible(element)) continue;
            if (normalize(getLabel(element)) === 'new chat') return element;
        }
        return null;
    }

    function newChatDiagnostics() {
        var labels = [];
        var elements = document.querySelectorAll('a, button, [role="button"]');
        var limit = Math.min(elements.length, 80);
        var i;
        var label;
        for (i = 0; i < limit; i += 1) {
            if (!isVisible(elements[i])) continue;
            label = normalize(getLabel(elements[i]));
            if (label) labels.push(label.slice(0, 100));
        }
        console.warn('[PASI] Visible control labels:', labels);
        return 'Visible controls logged to console.';
    }

    function isNewChatReady(previousUrl) {
        var composer = findComposer();
        if (!composer) return false;
        if (window.location.href !== previousUrl) return true;
        return !isGenerating();
    }

    async function startPrompt(operation) {
        var composer = await waitForComposer();
        if (!composer) throw new Error('Could not find ChatGPT composer.');
        clearComposer(composer);
        insertText(composer, operation.prompt);

        var verifiedComposer = await waitForPromptInsertion(operation.prompt);
        if (!verifiedComposer) {
            console.warn('[PASI] Prompt verification did not observe the expected text; continuing to submission diagnostics.');
        }

        var sendButton = await waitForSendButton();
        if (!sendButton) {
            throw new Error('Could not find ChatGPT send button. ' + submissionDiagnostics(operation.prompt));
        }

        await submitPromptWithRecovery(operation.prompt, sendButton);
        await waitUntilGenerationOrSubmissionSettles(operation.operation_id, operation.prompt);
        await reportFinished(operation.operation_id, false);
        console.log('[PASI] Operation completed:', operation.operation_id);
    }

    async function waitForComposer() {
        var startTime = Date.now();
        while (Date.now() - startTime < COMPOSER_TIMEOUT_MS) {
            var composer = findComposer();
            if (composer && !isGenerating()) return composer;
            await sleep(250);
        }
        return null;
    }

    function findComposer() {
        var selectors = [
            '#prompt-textarea',
            'textarea[data-id="root"]',
            'textarea',
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]'
        ];
        var i;
        var j;
        var elements;
        for (i = 0; i < selectors.length; i += 1) {
            elements = document.querySelectorAll(selectors[i]);
            for (j = 0; j < elements.length; j += 1) {
                if (isVisible(elements[j])) return elements[j];
            }
        }
        return null;
    }

    function findComposerContaining(expected) {
        var selectors = [
            '#prompt-textarea',
            'textarea[data-id="root"]',
            'textarea',
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]'
        ];
        var i;
        var j;
        var elements;
        var actual;
        for (i = 0; i < selectors.length; i += 1) {
            elements = document.querySelectorAll(selectors[i]);
            for (j = 0; j < elements.length; j += 1) {
                if (!isVisible(elements[j])) continue;
                actual = readComposerText(elements[j]);
                if (actual.indexOf(expected) !== -1) return elements[j];
            }
        }
        return null;
    }

    async function waitForPromptInsertion(expected) {
        var startTime = Date.now();
        var composer;
        while (Date.now() - startTime < PROMPT_VERIFY_TIMEOUT_MS) {
            composer = findComposerContaining(expected);
            if (composer) {
                console.log('[PASI] Prompt insertion verified.');
                return composer;
            }
            await sleep(200);
        }
        return null;
    }

    async function waitForSendButton() {
        var startTime = Date.now();
        while (Date.now() - startTime < SEND_BUTTON_TIMEOUT_MS) {
            var button = findSendButton();
            if (button) return button;
            await sleep(250);
        }
        return null;
    }

    function findSendButton() {
        var selectors = [
            'button[data-testid="send-button"]',
            'button[aria-label="Send prompt"]',
            'button[aria-label="Send message"]',
            'button[type="submit"]'
        ];
        var i;
        var j;
        var elements;
        var element;
        for (i = 0; i < selectors.length; i += 1) {
            elements = document.querySelectorAll(selectors[i]);
            for (j = 0; j < elements.length; j += 1) {
                element = elements[j];
                if (isVisible(element) && !isDisabled(element)) return element;
            }
        }
        elements = document.querySelectorAll('button, [role="button"]');
        for (i = 0; i < elements.length; i += 1) {
            element = elements[i];
            if (!isVisible(element) || isDisabled(element)) continue;
            var label = normalize(getLabel(element));
            if (label.indexOf('send prompt') !== -1 || label.indexOf('send message') !== -1 || label === 'send') return element;
        }
        return null;
    }

    async function submitPromptWithRecovery(expected, initialButton) {
        var attempt = 0;
        var composer;
        var button = initialButton;

        while (attempt < 3) {
            attempt += 1;
            composer = findComposerContaining(expected) || findComposer();
            if (!composer) throw new Error('Composer disappeared before submission.');

            button = findSendButton() || button;
            if (button && !isDisabled(button) && isVisible(button)) {
                console.log('[PASI] Submit attempt ' + attempt + ': clicking Send.');
                button.click();
            } else {
                console.log('[PASI] Submit attempt ' + attempt + ': falling back to form/keyboard submission.');
                if (!requestComposerSubmit(composer)) {
                    dispatchEnter(composer);
                }
            }

            if (await waitForSubmissionTransition(expected, SUBMISSION_TIMEOUT_MS)) {
                console.log('[PASI] ChatGPT accepted the prompt after submit attempt ' + attempt + '.');
                return;
            }

            if (attempt < 3) {
                await sleep(SUBMISSION_RETRY_DELAY_MS);
                button = findSendButton();
            }
        }

        console.warn('[PASI] Prompt submission did not transition the composer. ' + submissionDiagnostics(expected));
        throw new Error('ChatGPT prompt submission did not leave the composer after repeated send attempts.');
    }

    function requestComposerSubmit(composer) {
        var form = composer.closest('form');
        if (!form) return false;
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit(findSendButton() || undefined);
            return true;
        }
        return false;
    }

    async function waitForSubmissionTransition(expected, timeoutMs) {
        var startTime = Date.now();
        while (Date.now() - startTime < timeoutMs) {
            if (isGenerating()) return true;
            if (!findComposerContaining(expected)) return true;
            await sleep(150);
        }
        return false;
    }

    async function waitUntilGenerationOrSubmissionSettles(operationId, expected) {
        var startTime = Date.now();
        var sawGeneration = false;
        var submissionDeadline = Date.now() + SUBMISSION_TIMEOUT_MS;

        while (Date.now() - startTime < GENERATION_TIMEOUT_MS) {
            if (isGenerating()) {
                sawGeneration = true;
                submissionDeadline = Date.now() + GENERATION_TIMEOUT_MS;
                await sendHeartbeat(operationId);
                await sleep(GENERATION_POLL_MS);
                continue;
            }

            if (sawGeneration) {
                await sleep(750);
                if (!isGenerating()) return;
            } else if (!findComposerContaining(expected)) {
                await sleep(750);
                if (!isGenerating() && !findComposerContaining(expected)) return;
            } else if (Date.now() >= submissionDeadline) {
                throw new Error('ChatGPT prompt remained in the composer after submission.');
            }

            await sleep(GENERATION_POLL_MS);
        }

        throw new Error('ChatGPT generation timed out.');
    }

    function submissionDiagnostics(expected) {
        var composer = findComposerContaining(expected) || findComposer();
        var buttons = document.querySelectorAll('button, [role="button"]');
        var controls = [];
        var i;
        var label;
        var element;
        for (i = 0; i < Math.min(buttons.length, 80); i += 1) {
            element = buttons[i];
            if (!isVisible(element)) continue;
            label = normalize(getLabel(element));
            if (label) controls.push({ label: label.slice(0, 120), disabled: isDisabled(element) });
        }
        console.warn('[PASI] Submission diagnostics:', {
            composer_found: Boolean(composer),
            composer_text_length: composer ? readComposerText(composer).length : 0,
            expected_length: String(expected || '').length,
            is_generating: isGenerating(),
            active_element: document.activeElement ? document.activeElement.tagName : null,
            controls: controls
        });
        return 'Submission diagnostics logged to console.';
    }

    function isGenerating() {
        var selectors = [
            'button[data-testid="stop-button"]',
            'button[aria-label="Stop generating"]',
            'button[aria-label*="Stop"]'
        ];
        var i;
        var element;
        for (i = 0; i < selectors.length; i += 1) {
            element = document.querySelector(selectors[i]);
            if (element && isVisible(element)) return true;
        }
        return false;
    }

    function clearComposer(element) {
        element.focus();
        if (isTextControl(element)) {
            setNativeValue(element, '');
            element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
            return;
        }
        element.textContent = '';
        element.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'deleteContentBackward' }));
    }

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

    function dispatchEnter(element) {
        element.focus();
        var eventInit = {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true
        };
        element.dispatchEvent(new KeyboardEvent('keydown', eventInit));
        element.dispatchEvent(new KeyboardEvent('keypress', eventInit));
        element.dispatchEvent(new KeyboardEvent('keyup', eventInit));
    }

    function setNativeValue(element, value) {
        var prototype = Object.getPrototypeOf(element);
        var descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
        if (descriptor && descriptor.set) descriptor.set.call(element, value);
        else element.value = value;
    }

    function readComposerText(element) {
        if (!element) return '';
        if (isTextControl(element)) {
            return String(element.value || element.getAttribute('value') || '');
        }
        return String(element.innerText || element.textContent || '');
    }

    function isTextControl(element) {
        return Boolean(element) && (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT');
    }

    function isDisabled(element) {
        return Boolean(element) && (
            element.disabled === true ||
            element.getAttribute('disabled') !== null ||
            element.getAttribute('aria-disabled') === 'true'
        );
    }

    function getLabel(element) {
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

    function normalize(value) {
        return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function isVisible(element) {
        if (!element) return false;
        var style = window.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && element.getClientRects().length > 0;
    }

    async function sendHeartbeat(operationId) {
        try {
            await bridgeRequest('/chat/heartbeat', { method: 'POST', body: { operation_id: operationId } });
        } catch (error) {
            console.warn('[PASI] Heartbeat failed:', error);
        }
    }

    async function reportFinished(operationId, responseObserved) {
        var response = await bridgeRequest('/chat/finished', {
            method: 'POST',
            body: {
                operation_id: operationId,
                chat_url: window.location.href,
                response_text_available: Boolean(responseObserved)
            }
        });
        if (!response.ok) throw new Error('Bridge completion failed: HTTP ' + response.status);
    }

    async function reportFailure(operationId, error) {
        try {
            await bridgeRequest('/chat/failed', {
                method: 'POST',
                body: {
                    operation_id: operationId,
                    error: error instanceof Error ? error.message : String(error)
                }
            });
        } catch (reportError) {
            console.error('[PASI] Failed to report operation failure:', reportError);
        }
    }

    function sleep(milliseconds) {
        return new Promise(function (resolve) { setTimeout(resolve, milliseconds); });
    }
})();
