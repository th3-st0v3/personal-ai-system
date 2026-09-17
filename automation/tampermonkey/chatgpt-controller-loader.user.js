// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.1.0
// @description  Conditionally loads a verified PASI ChatGPT controller release from the trusted main branch.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      raw.githubusercontent.com
// ==/UserScript==

(function () {
    'use strict';

    var MANIFEST_URL = 'https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/tampermonkey/controller-sync.json';
    var TRUSTED_SOURCE_PREFIX = 'https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/';
    var POLL_INTERVAL_MS = 60000;
    var CHECK_TIMEOUT_MS = 10000;
    var LAST_VERSION_KEY = 'pasi_controller_synced_version';
    var LAST_HASH_KEY = 'pasi_controller_synced_git_blob_sha';

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
            if (installedVersion === manifest.version && installedHash === manifest.git_blob_sha) return;

            var source = await requestText(manifest.source_url);
            var blobSha = await gitBlobSha1(source);
            if (blobSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Controller Git blob mismatch; refusing to execute update.', {
                    expected: manifest.git_blob_sha,
                    actual: blobSha
                });
                return;
            }

            console.log('[PASI Loader] Verified controller release ' + manifest.version + '; activating.');
            GM_setValue(LAST_VERSION_KEY, manifest.version);
            GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
            eval(source);
        } catch (error) {
            console.warn('[PASI Loader] Controller synchronization check failed:', error);
        }
    }

    function isValidManifest(manifest) {
        return typeof manifest.version === 'string' &&
            /^\d+\.\d+\.\d+$/.test(manifest.version) &&
            typeof manifest.source_url === 'string' &&
            manifest.source_url.indexOf(TRUSTED_SOURCE_PREFIX) === 0 &&
            typeof manifest.git_blob_sha === 'string' &&
            /^[a-f0-9]{40}$/i.test(manifest.git_blob_sha);
    }

    async function gitBlobSha1(text) {
        var data = new TextEncoder().encode(text);
        var header = new TextEncoder().encode('blob ' + data.byteLength + '\0');
        var combined = new Uint8Array(header.byteLength + data.byteLength);
        combined.set(header, 0);
        combined.set(data, header.byteLength);
        var digest = await crypto.subtle.digest('SHA-1', combined);
        var bytes = new Uint8Array(digest);
        var output = '';
        for (var i = 0; i < bytes.length; i += 1) {
            output += bytes[i].toString(16).padStart(2, '0');
        }
        return output;
    }
})();
