// ==UserScript==
// @name         PASI Browser Page Observer
// @namespace    http://tampermonkey.net
// @version      1.0.0
// @description  Extracts a compact, screenshot-free page summary for the Personal AI System.
// @author       AI Assistant
// @match        *://*/*
// @noframes
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

        if (window.top !== window.self) {
        return;
    }

    /*
     * ============================================================
     * CONFIGURATION
     * ============================================================
     *
     * This observer intentionally does NOT capture screenshots.
     *
     * It produces:
     *   - page summary
     *   - visible text
     *   - interactive elements
     *   - stable element IDs
     *   - basic layout/visibility metadata
     *
     * The result is stored locally and can also be copied from
     * the console or requested through the PASIObserver API.
     */

    const CONFIG = {
        maxVisibleTextChars: 12000,
        maxElements: 300,
        maxTextPerElement: 300,
        maxAttributeLength: 300,
        storageKey: 'pasi-page-observation',
        idAttribute: 'data-pasi-id'
    };

    const BRIDGE_URL =
        'http://127.0.0.1:8765';

    const OBSERVER_VERSION = '1.0.0';

    /*
     * ============================================================
     * PUBLIC API
     * ============================================================
     *
     * Available from the page console:
     *
     *   PASIObserver.capture()
     *   PASIObserver.getLast()
     *   PASIObserver.print()
     *   PASIObserver.copy()
     */

    unsafeWindow.PASIObserver = {
        capture,
        getLast,
        print,
        copy
    };

    /*
     * ============================================================
     * INITIALIZATION
     * ============================================================
     */

    console.log(
        '[PASI Observer] Loaded.'
    );

    /*
     * ============================================================
     * MAIN CAPTURE
     * ============================================================
     */

    function capture() {
        const observation = {
            schema_version: OBSERVER_VERSION,
            captured_at: new Date().toISOString(),

            page: extractPageSummary(),

            visible_text: extractVisibleText(),

            interactive_elements:
                extractInteractiveElements(),

            landmarks:
                extractLandmarks()
        };

        saveObservation(
            observation
        );

        console.log(
            '[PASI Observer] Observation captured:',
            observation
        );

        return observation;
    }

    /*
     * ============================================================
     * PAGE SUMMARY
     * ============================================================
     */

    function extractPageSummary() {
        return {
            url: normalizeUrl(
                window.location.href
            ),

            origin:
                window.location.origin,

            title:
                cleanText(
                    document.title || ''
                ),

            language:
                document.documentElement
                    ?.getAttribute('lang') || null,

            ready_state:
                document.readyState,

            viewport: {
                width:
                    window.innerWidth,

                height:
                    window.innerHeight,

                device_pixel_ratio:
                    window.devicePixelRatio || 1
            },

            document_dimensions: {
                width:
                    document.documentElement
                        ?.scrollWidth || 0,

                height:
                    document.documentElement
                        ?.scrollHeight || 0
            }
        };
    }

    /*
     * ============================================================
     * VISIBLE TEXT
     * ============================================================
     */

    function extractVisibleText() {
        const root =
            document.body;

        if (!root) {
            return '';
        }

        const parts = [];

        const walker =
            document.createTreeWalker(
                root,
                NodeFilter.SHOW_TEXT
            );

        let node;

        while (
            (node = walker.nextNode())
        ) {
            if (
                parts.join(' ').length >=
                CONFIG.maxVisibleTextChars
            ) {
                break;
            }

            const parent =
                node.parentElement;

            if (!parent) {
                continue;
            }

            if (
                !isVisible(parent)
            ) {
                continue;
            }

            if (
                isIgnoredElement(parent)
            ) {
                continue;
            }

            const text =
                cleanText(
                    node.nodeValue || ''
                );

            if (!text) {
                continue;
            }

            parts.push(text);
        }

        return truncate(
            deduplicateAdjacentText(parts)
                .join(' '),
            CONFIG.maxVisibleTextChars
        );
    }

    /*
     * ============================================================
     * INTERACTIVE ELEMENTS
     * ============================================================
     */

    function extractInteractiveElements() {
        const selectors = [
            'a[href]',
            'button',
            'input',
            'textarea',
            'select',
            'option',
            '[role="button"]',
            '[role="link"]',
            '[role="textbox"]',
            '[role="checkbox"]',
            '[role="radio"]',
            '[role="switch"]',
            '[role="tab"]',
            '[role="menuitem"]',
            '[contenteditable="true"]'
        ];

        const nodes =
            document.querySelectorAll(
                selectors.join(',')
            );

        const results = [];

        for (
            const element of nodes
        ) {
            if (
                results.length >=
                CONFIG.maxElements
            ) {
                break;
            }

            if (
                !isVisible(element)
            ) {
                continue;
            }

            if (
                !isInteractable(element)
            ) {
                continue;
            }

            const id =
                ensureStableElementId(
                    element
                );

            const rect =
                element.getBoundingClientRect();

            results.push({
                id,

                tag:
                    element.tagName
                        .toLowerCase(),

                role:
                    getRole(element),

                type:
                    getInputType(element),

                name:
                    getAccessibleName(
                        element
                    ),

                control:
                    classifyInteractiveElement(
                        element,
                        getRole(element),
                        getAccessibleName(element)
                    ),

                text:
                    truncate(
                        cleanText(
                            element.innerText ||
                            element.textContent ||
                            ''
                        ),
                        CONFIG.maxTextPerElement
                    ),

                placeholder:
                    truncate(
                        element.getAttribute(
                            'placeholder'
                        ) || '',
                        CONFIG.maxAttributeLength
                    ) || null,

                href:
                    element instanceof
                        HTMLAnchorElement
                        ? normalizeUrl(
                            element.href
                        )
                        : null,

                value:
                    getSafeValue(element),

                disabled:
                    Boolean(
                        element.disabled
                    ),

                checked:
                    getCheckedState(element),

                position: {
                    x:
                        Math.round(rect.x),

                    y:
                        Math.round(rect.y),

                    width:
                        Math.round(rect.width),

                    height:
                        Math.round(rect.height)
                }
            });
        }

        return results;
    }

    function classifyInteractiveElement(
        element,
        role,
        name
    ) {
        const normalizedName =
            cleanText(
                name || ''
            ).toLowerCase();

        if (
            role === 'textbox' &&
            (
                normalizedName ===
                    'chat with chatgpt' ||
                element.matches(
                    '#prompt-textarea'
                ) ||
                element.isContentEditable
            )
        ) {
            return 'composer';
        }

        if (
            normalizedName === 'new chat'
        ) {
            return 'new_chat';
        }

        if (
            normalizedName === 'add files and more'
        ) {
            return 'attach';
        }

        if (
            normalizedName === 'switch model'
        ) {
            return 'model_selector';
        }

        if (
            normalizedName === 'start dictation'
        ) {
            return 'dictation';
        }

        if (
            normalizedName === 'start voice'
        ) {
            return 'voice';
        }

        if (
            normalizedName === 'send message' ||
            normalizedName === 'send'
        ) {
            return 'submit';
        }

        if (
            normalizedName === 'copy response'
        ) {
            return 'copy_response';
        }

        if (
            normalizedName === 'copy message'
        ) {
            return 'copy_message';
        }

        if (
            normalizedName === 'edit message'
        ) {
            return 'edit_message';
        }

        return null;
    }

    /*
     * ============================================================
     * LANDMARKS
     * ============================================================
     */

    function extractLandmarks() {
        const selectors = [
            'header',
            'nav',
            'main',
            'aside',
            'footer',
            '[role="banner"]',
            '[role="navigation"]',
            '[role="main"]',
            '[role="complementary"]',
            '[role="contentinfo"]'
        ];

        const nodes =
            document.querySelectorAll(
                selectors.join(',')
            );

        const results = [];

        for (
            const element of nodes
        ) {
            if (
                !isVisible(element)
            ) {
                continue;
            }

            const rect =
                element.getBoundingClientRect();

            results.push({
                tag:
                    element.tagName
                        .toLowerCase(),

                role:
                    getRole(element),

                name:
                    getAccessibleName(
                        element
                    ),

                position: {
                    x:
                        Math.round(rect.x),

                    y:
                        Math.round(rect.y),

                    width:
                        Math.round(rect.width),

                    height:
                        Math.round(rect.height)
                }
            });
        }

        return results;
    }

    /*
     * ============================================================
     * STABLE ELEMENT IDS
     * ============================================================
     */

    function ensureStableElementId(
        element
    ) {
        const existing =
            element.getAttribute(
                CONFIG.idAttribute
            );

        if (existing) {
            return existing;
        }

        const stableParts = [];

        const tag =
            element.tagName
                .toLowerCase();

        stableParts.push(tag);

        /*
         * Prefer attributes that normally remain
         * stable across page renders.
         */

        const explicitId =
            element.getAttribute('id');

        if (
            explicitId &&
            isStableAttribute(explicitId)
        ) {
            stableParts.push(
                `id-${sanitizeIdPart(explicitId)}`
            );
        }

        const name =
            element.getAttribute('name');

        if (
            name &&
            isStableAttribute(name)
        ) {
            stableParts.push(
                `name-${sanitizeIdPart(name)}`
            );
        }

        const ariaLabel =
            element.getAttribute(
                'aria-label'
            );

        if (ariaLabel) {
            stableParts.push(
                `aria-${sanitizeIdPart(
                    ariaLabel
                )}`
            );
        }

        const testId =
            element.getAttribute(
                'data-testid'
            );

        if (testId) {
            stableParts.push(
                `test-${sanitizeIdPart(testId)}`
            );
        }

        /*
         * Add a structural path so otherwise identical
         * elements can still be distinguished.
         */

        const path =
            getStructuralPath(
                element
            );

        stableParts.push(
            `p-${path}`
        );

        /*
         * Hash the descriptive identity into a compact ID.
         */

        const fingerprint =
            stableParts.join('|');

        const hash =
            fnv1aHash(
                fingerprint
            );

        const finalId =
            `pasi-${tag}-${hash}`;

        element.setAttribute(
            CONFIG.idAttribute,
            finalId
        );

        return finalId;
    }

    /*
     * ============================================================
     * STRUCTURAL PATH
     * ============================================================
     */

    function getStructuralPath(
        element
    ) {
        const parts = [];

        let current =
            element;

        let depth = 0;

        while (
            current &&
            current !== document.body &&
            depth < 8
        ) {
            let index = 0;

            let sibling =
                current;

            while (
                (sibling =
                    sibling.previousElementSibling)
            ) {
                index++;
            }

            parts.unshift(
                `${current.tagName.toLowerCase()}${index}`
            );

            current =
                current.parentElement;

            depth++;
        }

        return parts.join('.');
    }

    /*
     * ============================================================
     * ACCESSIBILITY
     * ============================================================
     */

    function getAccessibleName(
        element
    ) {
        const ariaLabel =
            cleanText(
                element.getAttribute(
                    'aria-label'
                ) || ''
            );

        if (ariaLabel) {
            return truncate(
                ariaLabel,
                CONFIG.maxAttributeLength
            );
        }

        const labelledBy =
            element.getAttribute(
                'aria-labelledby'
            );

        if (labelledBy) {
            const ids =
                labelledBy
                    .split(/\s+/)
                    .filter(Boolean);

            const text =
                ids
                    .map(id => {
                        const label =
                            document.getElementById(
                                id
                            );

                        return label
                            ? cleanText(
                                label.textContent ||
                                ''
                            )
                            : '';
                    })
                    .filter(Boolean)
                    .join(' ');

            if (text) {
                return truncate(
                    text,
                    CONFIG.maxAttributeLength
                );
            }
        }

        if (
            element instanceof
                HTMLInputElement ||
            element instanceof
                HTMLTextAreaElement ||
            element instanceof
                HTMLSelectElement
        ) {
            const associated =
                findAssociatedLabel(
                    element
                );

            if (associated) {
                return truncate(
                    cleanText(
                        associated.textContent ||
                        ''
                    ),
                    CONFIG.maxAttributeLength
                );
            }
        }

        const title =
            cleanText(
                element.getAttribute(
                    'title'
                ) || ''
            );

        if (title) {
            return truncate(
                title,
                CONFIG.maxAttributeLength
            );
        }

        return truncate(
            cleanText(
                element.innerText ||
                element.textContent ||
                ''
            ),
            CONFIG.maxAttributeLength
        );
    }

    function findAssociatedLabel(
        element
    ) {
        if (!element.id) {
            return null;
        }

        return document.querySelector(
            `label[for="${cssEscape(
                element.id
            )}"]`
        );
    }

    /*
     * ============================================================
     * ELEMENT STATE
     * ============================================================
     */

    function getRole(element) {
        return (
            element.getAttribute('role') ||
            inferRole(element)
        );
    }

    function inferRole(element) {
        const tag =
            element.tagName.toLowerCase();

        switch (tag) {
            case 'button':
                return 'button';

            case 'a':
                return 'link';

            case 'input':
                return 'textbox';

            case 'textarea':
                return 'textbox';

            case 'select':
                return 'combobox';

            default:
                return null;
        }
    }

    function getInputType(element) {
        if (
            element instanceof
            HTMLInputElement
        ) {
            return element.type ||
                'text';
        }

        if (
            element instanceof
            HTMLButtonElement
        ) {
            return element.type ||
                'button';
        }

        return null;
    }

    function getSafeValue(element) {
        if (
            element instanceof
                HTMLInputElement
        ) {
            if (
                element.type === 'password'
            ) {
                return '[REDACTED]';
            }

            return truncate(
                element.value || '',
                CONFIG.maxAttributeLength
            ) || null;
        }

        if (
            element instanceof
                HTMLTextAreaElement
        ) {
            return truncate(
                element.value || '',
                CONFIG.maxAttributeLength
            ) || null;
        }

        if (
            element instanceof
                HTMLSelectElement
        ) {
            return truncate(
                element.value || '',
                CONFIG.maxAttributeLength
            ) || null;
        }

        return null;
    }

    function getCheckedState(element) {
        if (
            element instanceof
                HTMLInputElement
        ) {
            if (
                element.type === 'checkbox' ||
                element.type === 'radio'
            ) {
                return element.checked;
            }
        }

        return null;
    }

    /*
     * ============================================================
     * VISIBILITY / INTERACTIVITY
     * ============================================================
     */

    function isVisible(element) {
        if (!element) {
            return false;
        }

        if (
            element.getAttribute(
                'aria-hidden'
            ) === 'true'
        ) {
            return false;
        }

        const style =
            window.getComputedStyle(
                element
            );

        if (
            style.display === 'none' ||
            style.visibility === 'hidden' ||
            style.opacity === '0'
        ) {
            return false;
        }

        const rect =
            element.getBoundingClientRect();

        return (
            rect.width > 0 &&
            rect.height > 0
        );
    }

    function isInteractable(element) {
        if (
            element.disabled === true
        ) {
            return false;
        }

        if (
            element.getAttribute(
                'aria-disabled'
            ) === 'true'
        ) {
            return false;
        }

        if (
            element.hasAttribute(
                'inert'
            )
        ) {
            return false;
        }

        return true;
    }

    function isIgnoredElement(element) {
        const tag =
            element.tagName
                .toLowerCase();

        return [
            'script',
            'style',
            'noscript',
            'template',
            'svg'
        ].includes(tag);
    }

    /*
     * ============================================================
     * TEXT UTILITIES
     * ============================================================
     */

    function cleanText(text) {
        return String(text)
            .replace(/\s+/g, ' ')
            .trim();
    }

    function truncate(
        text,
        maxLength
    ) {
        if (
            text.length <=
            maxLength
        ) {
            return text;
        }

        return (
            text.slice(
                0,
                maxLength - 1
            ) + '…'
        );
    }

    function deduplicateAdjacentText(
        parts
    ) {
        const result = [];

        for (
            const part of parts
        ) {
            if (
                result.length === 0 ||
                result[result.length - 1] !==
                    part
            ) {
                result.push(part);
            }
        }

        return result;
    }

    /*
     * ============================================================
     * URL UTILITIES
     * ============================================================
     */

    function normalizeUrl(url) {
        try {
            const parsed =
                new URL(
                    url,
                    window.location.href
                );

            /*
             * Remove fragments because they are usually
             * irrelevant to page identity.
             */

            parsed.hash = '';

            return parsed.href;
        } catch {
            return String(url || '');
        }
    }

    /*
     * ============================================================
     * ID UTILITIES
     * ============================================================
     */

    function sanitizeIdPart(value) {
        return String(value)
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 80);
    }

    function isStableAttribute(value) {
        if (!value) {
            return false;
        }

        /*
         * Ignore IDs that look auto-generated.
         */

        if (
            /^[:]?r[a-z0-9]+$/i.test(value)
        ) {
            return false;
        }

        if (
            /^[a-f0-9]{16,}$/i.test(value)
        ) {
            return false;
        }

        return true;
    }

    function fnv1aHash(text) {
        let hash =
            0x811c9dc5;

        for (
            let i = 0;
            i < text.length;
            i++
        ) {
            hash ^=
                text.charCodeAt(i);

            hash =
                Math.imul(
                    hash,
                    0x01000193
                );
        }

        return (
            hash >>> 0
        ).toString(16);
    }

    function cssEscape(value) {
        if (
            window.CSS &&
            typeof window.CSS.escape ===
                'function'
        ) {
            return window.CSS.escape(
                value
            );
        }

        return String(value)
            .replace(
                /([ !"#$%&'()*+,.\/:;<=>?@[\\\]^`{|}~])/g,
                '\\$1'
            );
    }

    /*
     * ============================================================
     * LOCAL STORAGE
     * ============================================================
     */

    function sendToBridge(
        observation
    ) {
        return new Promise(
            (resolve) => {
                GM_xmlhttpRequest({
                    method: 'POST',

                    url:
                        `${BRIDGE_URL}/browser/observation`,

                    headers: {
                        'Content-Type':
                            'application/json'
                    },

                    data:
                        JSON.stringify({
                            observation
                        }),

                    timeout: 5000,

                    onload(response) {
                        if (
                            response.status >= 200 &&
                            response.status < 300
                        ) {
                            console.log(
                                '[PASI Observer] Observation sent to bridge.'
                            );

                            resolve(true);
                            return;
                        }

                        console.warn(
                            '[PASI Observer] Bridge rejected observation:',
                            response.status,
                            response.responseText
                        );

                        resolve(false);
                    },

                    onerror() {
                        console.warn(
                            '[PASI Observer] Bridge unavailable.'
                        );

                        resolve(false);
                    },

                    ontimeout() {
                        console.warn(
                            '[PASI Observer] Bridge request timed out.'
                        );

                        resolve(false);
                    }
                });
            }
        );
    }

    function saveObservation(
        observation
    ) {
        try {
            const serialized =
                JSON.stringify(
                    observation
                );

            GM_setValue(
                CONFIG.storageKey,
                serialized
            );

            sessionStorage.setItem(
                CONFIG.storageKey,
                serialized
            );

            sendToBridge(
                observation
            );

        } catch (error) {
            console.warn(
                '[PASI Observer] Could not save observation:',
                error
            );
        }
    }

    function getLast() {
        try {
            const raw =
                  GM_getValue(
                      CONFIG.storageKey,
                      null
                  );

            if (raw) {
                return JSON.parse(raw);
            }
        } catch (error) {
            console.warn(
                '[PASI Observer] Could not read stored observation:',
                error
            );
        }

    return null;
}

    /*
     * ============================================================
     * OUTPUT HELPERS
     * ============================================================
     */

    function print() {
        const observation =
            capture();

        console.log(
            JSON.stringify(
                observation,
                null,
                2
            )
        );

        return observation;
    }

    async function copy() {
        const observation =
            capture();

        const text =
            JSON.stringify(
                observation,
                null,
                2
            );

        try {
            await navigator.clipboard.writeText(
                text
            );

            console.log(
                '[PASI Observer] Observation copied to clipboard.'
            );

            return true;

        } catch (error) {
            console.warn(
                '[PASI Observer] Clipboard write failed:',
                error
            );

            return false;
        }
    }

    /*
     * ============================================================
     * AUTOMATIC INITIAL CAPTURE
     * ============================================================
     */

    setTimeout(
        () => {
            try {
                capture();
            } catch (error) {
                console.error(
                    '[PASI Observer] Initial capture failed:',
                    error
                );
            }
        },
        1000
    );

})();