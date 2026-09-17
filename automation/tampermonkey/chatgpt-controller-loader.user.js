// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.0.0
// @description  Conditionally loads a verified PASI ChatGPT controller release.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      raw.githubusercontent.com
// ==/UserScript==

(function () {
    'use strict';

    var MANIFEST_URL = 'https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/tampermonkey/controller-sync.json';
    var POLL_INTERVAL_MS = 60000;
    var CHECK_TIMEOUT_MS = 10000;
    var LAST_VERSION_KEY = 'pasi_controller_synced_version';
    var LAST_HASH_KEY = 'pasi_controller_synced_sha256';
    var ACTIVE_KEY = 'pasi_controller_loader_active';

    if (GM_getValue(ACTIVE_KEY, false)) {
        return;
    }
    GM_setValue(ACTIVE_KEY, true);

    console.log('[PASI Loader] Conditional controller loader active.');
    checkForPublishedController();
    setInterval(checkForPublishedController, POLL_INTERVAL_MS);

    function requestText(url) {
        return new Promise(function (resolve, reject) {
            GM_xmlhttpRequest({
                method: 'GET',
                url: url,
                timeout: CHECK_TIMEOUT_MS,
                headers: { 'Accept': 'application/json, text/plain, */*' },
                onload: function (response) {
                    if (response.status >= 200 && response.status < 300) {
                        resolve(response.responseText);
                    } else {
                        reject(new Error('HTTP ' + response.status));
                    }
                },
                onerror: function () { reject(new Error('request failed')); },
                ontimeout: function () { reject(new Error('request timed out')); }
            });
        });
    }

    async function checkForPublishedController() {
        try {
            var rawManifest = await requestText(MANIFEST_URL);
            var manifest = JSON.parse(rawManifest);
            if (!manifest || manifest.enabled !== true) return;
            if (!isValidManifest(manifest)) {
                console.error('[PASI Loader] Invalid controller sync manifest.');
                return;
            }

            var installedVersion = GM_getValue(LAST_VERSION_KEY, '');
            var installedHash = GM_getValue(LAST_HASH_KEY, '');
            if (installedVersion === manifest.version && installedHash === manifest.sha256) return;

            var source = await requestText(manifest.source_url);
            var digest = await sha256Hex(source);
            if (digest !== manifest.sha256.toLowerCase()) {
                console.error('[PASI Loader] Controller hash mismatch; refusing to execute update.', {
                    expected: manifest.sha256,
                    actual: digest
                });
                return;
            }

            console.log('[PASI Loader] Verified controller release ' + manifest.version + '; activating.');
            GM_setValue(LAST_VERSION_KEY, manifest.version);
            GM_setValue(LAST_HASH_KEY, manifest.sha256);
            eval(source);
        } catch (error) {
            console.warn('[PASI Loader] Controller synchronization check failed:', error);
        }
    }

    function isValidManifest(manifest) {
        return typeof manifest.version === 'string' &&
            /^\d+\.\d+\.\d+$/.test(manifest.version) &&
            typeof manifest.source_url === 'string' &&
            manifest.source_url.indexOf('https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/') === 0 &&
            typeof manifest.sha256 === 'string' &&
            /^[a-f0-9]{64}$/i.test(manifest.sha256);
    }

    async function sha256Hex(text) {
        var data = new TextEncoder().encode(text);
        var digest = await crypto.subtle.digest('SHA-256', data);
        var bytes = new Uint8Array(digest);
        var output = '';
        var i;
        for (i = 0; i < bytes.length; i += 1) {
            output += bytes[i].toString(16).padStart(2, '0');
        }
        return output;
    }
})();
