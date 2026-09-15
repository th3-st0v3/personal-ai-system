// ==UserScript==
// @name         Personal AI System - ChatGPT Controller
// @namespace    http://tampermonkey.net/
// @version      1.3
// @description  Connects ChatGPT to the local Personal AI System orchestrator.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    const BRIDGE_URL = 'http://127.0.0.1:8765';

    function bridgeRequest(path, options = {}) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url: `${BRIDGE_URL}${path}`,
                headers: options.body
                    ? { 'Content-Type': 'application/json' }
                    : undefined,
                data: options.body
                    ? JSON.stringify(options.body)
                    : undefined,
                timeout: 10000,

                onload(response) {
                    resolve({
                        ok: response.status >= 200 &&
                            response.status < 300,
                        status: response.status,
                        text: response.responseText,
                        async json() {
                            return JSON.parse(response.responseText);
                        }
                    });
                },

                onerror(error) {
                    reject(new Error(
                        `Bridge request failed: ${path}`
                    ));
                },

                ontimeout() {
                    reject(new Error(
                        `Bridge request timed out: ${path}`
                    ));
                }
            });
        });
    }

    const POLL_INTERVAL_MS = 1000;
    const GENERATION_POLL_MS = 500;
    const COMPOSER_TIMEOUT_MS = 15000;
    const SEND_BUTTON_TIMEOUT_MS = 10000;
    const GENERATION_TIMEOUT_MS = 60 * 60 * 1000;

    let activeOperationId = null;
    let processing = false;

    console.log(
        '[PASI] ChatGPT controller loaded.'
    );

    start().catch((error) => {
        console.error(
            '[PASI] Controller startup failed:',
            error
        );
    });

    async function start() {
        const healthy = await checkBridge();

        if (!healthy) {
            console.warn(
                '[PASI] Local bridge is not available at',
                BRIDGE_URL
            );

            return;
        }

        console.log(
            '[PASI] Local bridge connected.'
        );

        setInterval(
            pollForOperation,
            POLL_INTERVAL_MS
        );

        console.log(
            '[PASI] Polling for operations.'
        );
    }

    async function checkBridge() {
        try {
            const response = await bridgeRequest('/health');

            return response.ok;
        } catch (error) {
            return false;
        }
    }

    async function pollForOperation() {
        if (processing || activeOperationId !== null) {
            return;
        }

        try {
            const response = await bridgeRequest('/next-operation');

            if (!response.ok) {
                return;
            }

            const payload = await response.json();

            if (!payload.operation) {
                return;
            }

            const operation = payload.operation;

            activeOperationId =
                operation.operation_id;

            processing = true;

            console.log(
                '[PASI] Claimed operation:',
                operation
            );

            await processOperation(operation);

        } catch (error) {
            console.error(
                '[PASI] Operation processing failed:',
                error
            );

            if (activeOperationId !== null) {
                await reportFailure(
                    activeOperationId,
                    error
                );
            }

        } finally {
            activeOperationId = null;
            processing = false;
        }
    }

    async function processOperation(operation) {
        let observation = await getBrowserObservation();

        await waitUntilReady(observation);

        await sendHeartbeat(
            operation.operation_id
        );

        let composer =
            findComposer(observation);

        if (!composer) {
            observation = await getBrowserObservation();
            composer = findComposer(observation);
        }

        if (!composer) {
            throw new Error(
                'Could not find ChatGPT composer.'
            );
        }

        clearComposer(composer);

        insertText(
            composer,
            operation.prompt
        );

        await sleep(500);

        if (
            !composerContains(
                composer,
                operation.prompt
            )
        ) {
            throw new Error(
                'Prompt insertion could not be verified.'
            );
        }

        const sendButton =
            await waitForSendButton();

        if (!sendButton) {
            throw new Error(
                'Could not find ChatGPT send button.'
            );
        }

        if (sendButton.disabled) {
            throw new Error(
                'ChatGPT send button is disabled.'
            );
        }

        console.log(
            '[PASI] Sending operation:',
            operation.operation_id
        );

        sendButton.click();

        await waitUntilGenerationFinishes(
            operation.operation_id
        );

        await reportFinished(
            operation.operation_id
        );

        console.log(
            '[PASI] Operation completed:',
            operation.operation_id
        );
    }

    async function waitUntilReady(observation) {
        const start = Date.now();

        while (
            Date.now() - start <
            COMPOSER_TIMEOUT_MS
        ) {
            if (!isGenerating()) {
                const composer =
                    findComposer(observation);

                if (composer) {
                    return;
                }
            }

            await sleep(250);
        }

        throw new Error(
            'ChatGPT was not ready for a new operation.'
        );
    }

    async function getBrowserObservation() {
        try {
            const response =
                await bridgeRequest('/browser/observation');

            if (!response.ok) {
                return null;
            }

            const payload = await response.json();

            if (
                !payload ||
                typeof payload.observation !== 'object' ||
                payload.observation === null
            ) {
                return null;
            }

            return payload.observation;
        } catch (error) {
            console.warn(
                '[PASI] Browser observation unavailable:',
                error
            );

            return null;
        }
    }

    async function waitUntilGenerationFinishes(
        operationId
    ) {
        const start = Date.now();

        while (
            Date.now() - start <
            GENERATION_TIMEOUT_MS
        ) {
            if (!isGenerating()) {
                await sleep(750);

                if (!isGenerating()) {
                    return;
                }
            }

            await sendHeartbeat(
                operationId
            );

            await sleep(
                GENERATION_POLL_MS
            );
        }

        throw new Error(
            'ChatGPT generation timed out.'
        );
    }

    function findComposer(observation = null) {
        const semanticComposer =
            findComposerFromObservation(observation);

        if (semanticComposer) {
            return semanticComposer;
        }

        return findComposerWithSelectors();
    }

    function findComposerFromObservation(observation) {
        if (
            !observation ||
            !Array.isArray(observation.interactive_elements)
        ) {
            return null;
        }

        const semanticComposer =
            observation.interactive_elements.find(
                (element) =>
                    element &&
                    element.control === 'composer' &&
                    element.role === 'textbox' &&
                    typeof element.id === 'string' &&
                    element.id.length > 0
            );

        if (!semanticComposer) {
            return null;
        }

        const elements =
            document.querySelectorAll('[data-pasi-id]');

        for (const element of elements) {
            if (
                element.getAttribute('data-pasi-id') ===
                    semanticComposer.id &&
                isVisible(element)
            ) {
                return element;
            }
        }

        return null;
    }

    function findComposerWithSelectors() {
        const selectors = [
            '#prompt-textarea',
            'textarea[data-id="root"]',
            'textarea',
            '[contenteditable="true"]'
        ];

        for (const selector of selectors) {
            const elements =
                document.querySelectorAll(selector);

            for (const element of elements) {
                if (isVisible(element)) {
                    return element;
                }
            }
        }

        return null;
    }

    function clearComposer(element) {
        element.focus();

        if (
            element instanceof HTMLTextAreaElement ||
            element instanceof HTMLInputElement
        ) {
            setNativeValue(element, '');

            element.dispatchEvent(
                new Event('input', {
                    bubbles: true,
                    composed: true
                })
            );

            return;
        }

        const selection =
            window.getSelection();

        if (selection) {
            selection.removeAllRanges();

            const range =
                document.createRange();

            range.selectNodeContents(element);
            selection.addRange(range);
        }

        document.execCommand(
            'delete',
            false
        );
    }

    function insertText(element, text) {
        element.focus();

        if (
            element instanceof HTMLTextAreaElement ||
            element instanceof HTMLInputElement
        ) {
            setNativeValue(
                element,
                text
            );

            element.dispatchEvent(
                new Event('input', {
                    bubbles: true,
                    composed: true
                })
            );

            element.dispatchEvent(
                new Event('change', {
                    bubbles: true
                })
            );

            return;
        }

        const selection =
            window.getSelection();

        if (selection) {
            selection.removeAllRanges();

            const range =
                document.createRange();

            range.selectNodeContents(element);
            range.collapse(false);

            selection.addRange(range);
        }

        document.execCommand(
            'insertText',
            false,
            text
        );

        element.dispatchEvent(
            new InputEvent(
                'input',
                {
                    bubbles: true,
                    composed: true,
                    inputType: 'insertText',
                    data: text
                }
            )
        );
    }

    function composerContains(
        element,
        expected
    ) {
        let actual = '';

        if (
            element instanceof HTMLTextAreaElement ||
            element instanceof HTMLInputElement
        ) {
            actual = element.value || '';
        } else {
            actual =
                element.innerText ||
                element.textContent ||
                '';
        }

        return actual.includes(
            expected.slice(0, 100)
        );
    }

    function setNativeValue(
        element,
        value
    ) {
        const prototype =
            Object.getPrototypeOf(element);

        const descriptor =
            Object.getOwnPropertyDescriptor(
                prototype,
                'value'
            );

        if (
            descriptor &&
            descriptor.set
        ) {
            descriptor.set.call(
                element,
                value
            );
        } else {
            element.value = value;
        }
    }

    function findSendButton() {
        const selectors = [
            'button[data-testid="send-button"]',
            'button[aria-label="Send prompt"]',
            'button[aria-label="Send message"]'
        ];

        for (const selector of selectors) {
            const button =
                document.querySelector(
                    selector
                );

            if (
                button &&
                isVisible(button)
            ) {
                return button;
            }
        }

        const buttons =
            document.querySelectorAll(
                'button'
            );

        for (const button of buttons) {
            if (!isVisible(button)) {
                continue;
            }

            const label =
                getLabel(button)
                    .toLowerCase();

            if (
                label.includes('send prompt') ||
                label.includes('send message')
            ) {
                return button;
            }
        }

        return null;
    }

    async function waitForSendButton() {
        const start = Date.now();

        while (
            Date.now() - start <
            SEND_BUTTON_TIMEOUT_MS
        ) {
            const button =
                findSendButton();

            if (button) {
                return button;
            }

            await sleep(250);
        }

        return null;
    }

    function isGenerating() {
        const selectors = [
            'button[data-testid="stop-button"]',
            'button[aria-label="Stop generating"]',
            'button[aria-label*="Stop"]'
        ];

        for (const selector of selectors) {
            const element =
                document.querySelector(
                    selector
                );

            if (
                element &&
                isVisible(element)
            ) {
                return true;
            }
        }

        const buttons =
            document.querySelectorAll(
                'button'
            );

        for (const button of buttons) {
            if (!isVisible(button)) {
                continue;
            }

            const label =
                getLabel(button)
                    .toLowerCase();

            if (
                label.includes('stop generating') ||
                label === 'stop' ||
                label.includes('stop response')
            ) {
                return true;
            }
        }

        return false;
    }

    async function sendHeartbeat(
        operationId
    ) {
        try {
            await bridgeRequest('/chat/heartbeat', {
                method: 'POST',
                body: {
                    operation_id: operationId
                }
            });
        } catch (error) {
            console.warn(
                '[PASI] Heartbeat failed:',
                error
            );
        }
    }

    async function reportFinished(
        operationId
    ) {
        const response = await bridgeRequest('/chat/finished', {
            method: 'POST',
            body: {
                operation_id: operationId,
                chat_url: window.location.href
            }
        });

        if (!response.ok) {
            throw new Error(
                `Bridge completion failed: HTTP ${response.status}`
            );
        }
    }

    async function reportFailure(
        operationId,
        error
    ) {
        try {
            await bridgeRequest('/chat/failed', {
                method: 'POST',
                body: {
                    operation_id: operationId,
                    error: error instanceof Error
                        ? error.message
                        : String(error)
                }
            });
        } catch (reportError) {
            console.error(
                '[PASI] Failed to report failure:',
                reportError
            );
        }
    }

    function getLabel(element) {
        return [
            element.getAttribute(
                'aria-label'
            ),
            element.getAttribute(
                'title'
            ),
            element.textContent
        ]
            .filter(Boolean)
            .join(' ')
            .trim();
    }

    function isVisible(element) {
        if (!element) {
            return false;
        }

        const style =
            window.getComputedStyle(
                element
            );

        return (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0' &&
            element.getClientRects()
                .length > 0
        );
    }

    function sleep(ms) {
        return new Promise(
            resolve =>
                setTimeout(
                    resolve,
                    ms
                )
        );
    }

})();
