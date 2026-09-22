// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader (Deprecated)
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.8.0
// @description  Deprecated migration notice for the retired PASI Tampermonkey controller-distribution bootstrap.
// @match        https://chatgpt.com/*
// ==/UserScript==

(function () {
    'use strict';

    console.warn(
        '[PASI Loader] Deprecated: the Tampermonkey controller loader is migration-only and no longer participates in PASI runtime operation. ' +
        'Install and enable the native Chromium extension from automation/chromium/pasi-chatgpt instead.'
    );
})();
