// ==UserScript==
// @name         Personal AI System - ChatGPT Runtime Watchdog
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.0.0
// @description  Reports provider limits, auth challenges, and browser readiness to PASI during unattended ChatGPT automation.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    var BRIDGE_URL = 'http://127.0.0.1:8765';
    var INTERVAL_MS = 5000;
    var MAX_BODY_CHARS = 12000;
    var CONTEXT_MARKERS = [
        'conversation has reached its limit',
        'conversation is too long',
        'context limit reached',
        'start a new chat to continue'
    ];
    var USAGE_MARKERS = [
        'current usage limit',
        'usage limit reached',
        'free tier limit',
        'message limit',
        'daily limit',
        'weekly limit',
        'model usage limit',
        'rate limit',
        'too many requests',
        'try again later'
    ];
    var AUTH_MARKERS = [
        'log in to continue',
        'sign in to continue',
        "verify you're human",
        'security check',
        'captcha',
        'session has expired'
    ];

    function bridgePost(observation) {
        return new Promise(function (resolve) {
            GM_xmlhttpRequest({
                method: 'POST',
                url: BRIDGE_URL + '/browser/observation',
                headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify({ observation: observation }),
                timeout: 5000,
                onload: function () { resolve(); },
                onerror: function () { resolve(); },
                ontimeout: function () { resolve(); }
            });
        });
    }

    function normalize(value) {
        return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function bodyText() {
        return normalize(document.body ? document.body.innerText : '').slice(0, MAX_BODY_CHARS);
    }

    function containsAny(text, markers) {
        for (var i = 0; i < markers.length; i += 1) {
            if (text.indexOf(markers[i]) !== -1) return true;
        }
        return false;
    }

    function findComposer() {
        var selectors = [
            '#prompt-textarea',
            'textarea[data-id="root"]',
            'textarea',
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]'
        ];
        for (var i = 0; i < selectors.length; i += 1) {
            var nodes = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < nodes.length; j += 1) {
                if (isVisible(nodes[j])) return nodes[j];
            }
        }
        return null;
    }

    function isVisible(element) {
        if (!element) return false;
        var style = window.getComputedStyle(element);
        var rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }

    function chatUrl() {
        return /^https:\/\/chatgpt\.com\/c\//.test(window.location.href) ? window.location.href : null;
    }

    function inferThinkingEnabled() {
        var nodes = document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"], [data-state="on"], [data-state="active"]');
        for (var i = 0; i < nodes.length; i += 1) {
            if (isVisible(nodes[i]) && normalize(nodes[i].innerText || nodes[i].textContent || '').indexOf('thinking') !== -1) return true;
        }
        var controls = document.querySelectorAll('button, [role="button"], [role="option"], [role="menuitem"]');
        for (var j = 0; j < controls.length; j += 1) {
            if (!isVisible(controls[j])) continue;
            var text = normalize(controls[j].innerText || controls[j].textContent || '');
            if (text === 'thinking' || text.indexOf('thinking mode') !== -1) {
                if (controls[j].getAttribute('aria-current') === 'true' || controls[j].getAttribute('aria-checked') === 'true') return true;
            }
        }
        return null;
    }

    async function sample() {
        var text = bodyText();
        var contextExhausted = containsAny(text, CONTEXT_MARKERS);
        var providerUsageLimited = !contextExhausted && containsAny(text, USAGE_MARKERS);
        var authRequired = containsAny(text, AUTH_MARKERS);
        var observation = {
            schema_version: '1',
            captured_at: new Date().toISOString(),
            kind: 'chatgpt_health',
            chat_url: chatUrl(),
            provider_usage_limited: providerUsageLimited,
            auth_required: authRequired,
            conversation_context_exhausted: contextExhausted,
            thinking_enabled: inferThinkingEnabled(),
            page_visible: document.visibilityState !== 'hidden',
            composer_present: Boolean(findComposer()),
            signals: []
        };
        if (providerUsageLimited) observation.signals.push('provider_usage_limit');
        if (authRequired) observation.signals.push('auth_required');
        if (contextExhausted) observation.signals.push('conversation_context_exhausted');
        if (observation.thinking_enabled === false) observation.signals.push('thinking_not_confirmed');
        await bridgePost(observation);
    }

    console.log('[PASI Watchdog] ChatGPT runtime watchdog v1.0.0 active.');
    sample();
    setInterval(sample, INTERVAL_MS);
})();
