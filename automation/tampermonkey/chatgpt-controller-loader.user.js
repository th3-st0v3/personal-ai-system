// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.5.0
// @description  Loads a verified PASI ChatGPT controller and recovery companion from the local PASI runtime.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      127.0.0.1
// ==/UserScript==

(function () {
    'use strict';

    var LOCAL_MANIFEST_URL = 'http://127.0.0.1:8766/controller/manifest';
    var LOCAL_SOURCE_URL = 'http://127.0.0.1:8766/controller/source';
    var LOCAL_RECOVERY_SOURCE_URL = 'http://127.0.0.1:8766/recovery/source';
    var POLL_INTERVAL_MS = 30000;
    var CHECK_TIMEOUT_MS = 10000;
    var LAST_VERSION_KEY = 'pasi_controller_verified_version';
    var LAST_HASH_KEY = 'pasi_controller_verified_git_blob_sha';
    var ACTIVE_HASH_PROPERTY = '__PASI_CHATGPT_CONTROLLER_ACTIVE_HASH__';

    console.log('[PASI Loader] Local private-repository controller loader v1.5.0 active.');
    activateOrScheduleReload();
    setInterval(checkForPublishedController, POLL_INTERVAL_MS);

    function requestText(url, headers) {
        headers = headers || {};
        return new Promise(function (resolve, reject) {
            GM_xmlhttpRequest({
                method: 'GET',
                url: url,
                timeout: CHECK_TIMEOUT_MS,
                headers: headers,
                onload: function (response) {
                    if (response.status >= 200 && response.status < 300) {
                        resolve(response.responseText);
                        return;
                    }
                    var error = new Error('HTTP ' + response.status);
                    error.status = response.status;
                    reject(error);
                },
                onerror: function () { reject(new Error('request failed')); },
                ontimeout: function () { reject(new Error('request timed out')); }
            });
        });
    }

    async function activateOrScheduleReload() {
        try {
            var manifest = await loadLocalManifest();
            if (!manifest || manifest.enabled !== true) return;
            validateManifest(manifest);

            var activeHash = window[ACTIVE_HASH_PROPERTY] || '';
            if (activeHash && activeHash.toLowerCase() === manifest.git_blob_sha.toLowerCase()) {
                await activateRecovery(manifest);
                return;
            }

            var source = await requestText(LOCAL_SOURCE_URL, { 'Accept': 'text/plain, */*' });
            var blobSha = await gitBlobSha1(source);
            if (blobSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local controller Git blob mismatch; refusing to execute.', {
                    expected: manifest.git_blob_sha,
                    actual: blobSha
                });
                return;
            }

            var storedVersion = GM_getValue(LAST_VERSION_KEY, '');
            var storedHash = GM_getValue(LAST_HASH_KEY, '');
            if (activeHash && storedHash && storedHash !== manifest.git_blob_sha) {
                console.log('[PASI Loader] Verified controller update detected; refreshing the page before activation.');
                GM_setValue(LAST_VERSION_KEY, manifest.version);
                GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
                window.location.reload();
                return;
            }

            if (!activeHash && storedVersion === manifest.version && storedHash === manifest.git_blob_sha) {
                console.log('[PASI Loader] Verified controller release ' + manifest.version + ' is ready; activating after page load.');
            } else {
                GM_setValue(LAST_VERSION_KEY, manifest.version);
                GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
            }

            window[ACTIVE_HASH_PROPERTY] = manifest.git_blob_sha.toLowerCase();
            console.log('[PASI Loader] Verified controller release ' + manifest.version + '; activating.');
            eval(injectActiveOperationGetter(source));
            await activateRecovery(manifest);
        } catch (error) {
            console.warn('[PASI Loader] Controller synchronization check failed:', error);
        }
    }

    async function activateRecovery(manifest) {
        try {
            var recoverySource = await requestText(LOCAL_RECOVERY_SOURCE_URL, { 'Accept': 'text/plain, */*' });
            var recoverySha = await gitBlobSha1(recoverySource);
            if (recoverySha !== manifest.recovery_git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local recovery Git blob mismatch; refusing to execute.', {
                    expected: manifest.recovery_git_blob_sha,
                    actual: recoverySha
                });
                return;
            }
            eval(recoverySource);
            console.log('[PASI Loader] Verified recovery companion ' + manifest.recovery_version + '; activating.');
        } catch (error) {
            console.warn('[PASI Loader] Recovery companion synchronization failed; controller remains active:', error);
        }
    }

    async function checkForPublishedController() {
        try {
            var manifest = await loadLocalManifest();
            if (!manifest || manifest.enabled !== true) return;
            validateManifest(manifest);

            var activeHash = window[ACTIVE_HASH_PROPERTY] || '';
            if (!activeHash || activeHash.toLowerCase() === manifest.git_blob_sha.toLowerCase()) return;

            var source = await requestText(LOCAL_SOURCE_URL, { 'Accept': 'text/plain, */*' });
            var blobSha = await gitBlobSha1(source);
            if (blobSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local controller Git blob mismatch; refusing to reload.', {
                    expected: manifest.git_blob_sha,
                    actual: blobSha
                });
                return;
            }

            console.log('[PASI Loader] New verified controller release detected; reloading page for clean activation.');
            GM_setValue(LAST_VERSION_KEY, manifest.version);
            GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
            window.location.reload();
        } catch (error) {
            console.warn('[PASI Loader] Controller update check failed:', error);
        }
    }

    async function loadLocalManifest() {
        var raw = await requestText(LOCAL_MANIFEST_URL, { 'Accept': 'application/json, text/plain, */*' });
        return JSON.parse(raw);
    }

    function validateManifest(manifest) {
        if (typeof manifest.version !== 'string' || !/^\d+\.\d+\.\d+$/.test(manifest.version)) {
            throw new Error('Invalid controller manifest version.');
        }
        if (typeof manifest.git_blob_sha !== 'string' || !/^[a-f0-9]{40}$/i.test(manifest.git_blob_sha)) {
            throw new Error('Invalid controller manifest Git blob SHA.');
        }
        if (typeof manifest.recovery_version !== 'string' || !/^\d+\.\d+\.\d+$/.test(manifest.recovery_version)) {
            throw new Error('Invalid recovery manifest version.');
        }
        if (typeof manifest.recovery_git_blob_sha !== 'string' || !/^[a-f0-9]{40}$/i.test(manifest.recovery_git_blob_sha)) {
            throw new Error('Invalid recovery manifest Git blob SHA.');
        }
    }

    function injectActiveOperationGetter(source) {
        var needle = 'var activeOperationId = null;';
        var replacement = needle + "\n    try { window.__PASI_CHATGPT_ACTIVE_OPERATION__ = function () { return activeOperationId; }; } catch (_) {}";
        if (source.indexOf(needle) === -1) throw new Error('Controller source did not expose the expected active-operation binding.');
        return source.replace(needle, replacement);
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
