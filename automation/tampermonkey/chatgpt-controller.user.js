// ==UserScript==
// @name         Personal AI System - ChatGPT Controller
// @namespace    http://tampermonkey.net/
// @version      2.0.0
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
    var SEND_BUTTON_TIMEOUT_MS = 10000;
    var NEW_CHAT_TIMEOUT_MS = 15000;
    var GENERATION_POLL_MS = 500;
    var GENERATION_TIMEOUT_MS = 60 * 60 * 1000;

    var activeOperationId = null;
    var processing = false;

    console.log('[PASI] ChatGPT Controller v2.0.0 loaded.');
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
            await reportFinished(operation.operation_id, true);
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
        if (button.disabled || button.getAttribute('aria-disabled') === 'true') {
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
        await sleep(400);
        if (!composerContains(composer, operation.prompt)) {
            throw new Error('Prompt insertion could not be verified.');
        }
        var sendButton = await waitForSendButton();
        if (!sendButton) throw new Error('Could not find ChatGPT send button.');
        if (sendButton.disabled || sendButton.getAttribute('aria-disabled') === 'true') {
            throw new Error('ChatGPT send button is disabled.');
        }
        console.log('[PASI] Sending operation:', operation.operation_id);
        sendButton.click();
        await waitUntilGenerationFinishes(operation.operation_id);
        await reportFinished(operation.operation_id, true);
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
        for (i = 0; i < selectors.length; i += 1) {
            elements = document.querySelectorAll(selectors[i]);
            for (j = 0; j < elements.length; j += 1) {
                if (isVisible(elements[j])) return elements[j];
            }
        }
        elements = document.querySelectorAll('button, [role="button"]');
        for (i = 0; i < elements.length; i += 1) {
            if (!isVisible(elements[i])) continue;
            var label = normalize(getLabel(elements[i]));
            if (label.indexOf('send prompt') !== -1 || label.indexOf('send message') !== -1 || label === 'send') return elements[i];
        }
        return null;
    }

    async function waitUntilGenerationFinishes(operationId) {
        var startTime = Date.now();
        while (Date.now() - startTime < GENERATION_TIMEOUT_MS) {
            if (!isGenerating()) {
                await sleep(750);
                if (!isGenerating()) return;
            }
            await sendHeartbeat(operationId);
            await sleep(GENERATION_POLL_MS);
        }
        throw new Error('ChatGPT generation timed out.');
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
        if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
            setNativeValue(element, '');
            element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            return;
        }
        element.textContent = '';
        element.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'deleteContentBackward' }));
    }

    function insertText(element, text) {
        element.focus();
        if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
            setNativeValue(element, text);
            element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
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

    function setNativeValue(element, value) {
        var prototype = Object.getPrototypeOf(element);
        var descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
        if (descriptor && descriptor.set) descriptor.set.call(element, value);
        else element.value = value;
    }

    function composerContains(element, expected) {
        var actual = element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement
            ? element.value || ''
            : element.innerText || element.textContent || '';
        return actual.indexOf(expected) !== -1;
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
