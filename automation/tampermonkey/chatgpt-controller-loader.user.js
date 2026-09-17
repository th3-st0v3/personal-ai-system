// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.6.3
// @sandbox      DOM
// @description  Loads verified PASI ChatGPT controller and recovery releases from the local PASI runtime.
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
    var LAST_RECOVERY_VERSION_KEY = 'pasi_recovery_verified_version';
    var LAST_RECOVERY_HASH_KEY = 'pasi_recovery_verified_git_blob_sha';
    var ACTIVE_HASH_PROPERTY = '__PASI_CHATGPT_CONTROLLER_ACTIVE_HASH__';
    var ACTIVE_RECOVERY_HASH_PROPERTY = '__PASI_CHATGPT_RECOVERY_ACTIVE_HASH__';

    console.log('[PASI Loader] Verified PASI ChatGPT controller loader v1.6.3 active.');
    activateOrScheduleReload();
    setInterval(checkForPublishedController, POLL_INTERVAL_MS);

    function requestBytes(url, headers) {
        headers = headers || {};
        return new Promise(function (resolve, reject) {
            GM_xmlhttpRequest({
                method: 'GET',
                url: url,
                timeout: CHECK_TIMEOUT_MS,
                responseType: 'arraybuffer',
                headers: headers,
                onload: function (response) {
                    if (response.status >= 200 && response.status < 300) {
                        if (!(response.response instanceof ArrayBuffer)) {
                            reject(new Error('Expected ArrayBuffer response.'));
                            return;
                        }
                        resolve(new Uint8Array(response.response));
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

    function decodeUtf8(bytes) {
        return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    }

    async function requestText(url, headers) {
        return decodeUtf8(await requestBytes(url, headers));
    }

    async function activateOrScheduleReload() {
        try {
            var manifest = await loadLocalManifest();
            if (!manifest || manifest.enabled !== true) return;
            validateManifest(manifest);

            var activeHash = window[ACTIVE_HASH_PROPERTY] || '';
            var activeRecoveryHash = window[ACTIVE_RECOVERY_HASH_PROPERTY] || '';
            if (
                activeHash &&
                activeHash.toLowerCase() === manifest.git_blob_sha.toLowerCase() &&
                activeRecoveryHash &&
                activeRecoveryHash.toLowerCase() === manifest.recovery_git_blob_sha.toLowerCase()
            ) return;

            var sourceBytes = await requestBytes(LOCAL_SOURCE_URL, { 'Accept': 'application/octet-stream, text/plain, */*' });
            var blobSha = await gitBlobSha1Bytes(sourceBytes);
            console.log('[PASI Loader] Controller received bytes: ' + sourceBytes.byteLength);
            console.log('[PASI Loader] Controller received Git blob SHA: ' + blobSha);
            if (blobSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local controller Git blob mismatch; refusing to execute.', {
                    expected: manifest.git_blob_sha,
                    actual: blobSha
                });
                return;
            }

            var recoveryBytes = await requestBytes(LOCAL_RECOVERY_SOURCE_URL, { 'Accept': 'application/octet-stream, text/plain, */*' });
            var recoverySha = await gitBlobSha1Bytes(recoveryBytes);
            console.log('[PASI Loader] Recovery received bytes: ' + recoveryBytes.byteLength);
            console.log('[PASI Loader] Recovery received Git blob SHA: ' + recoverySha);
            if (recoverySha !== manifest.recovery_git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local recovery Git blob mismatch; refusing to execute.', {
                    expected: manifest.recovery_git_blob_sha,
                    actual: recoverySha
                });
                return;
            }

            var source = decodeUtf8(sourceBytes);
            var recoverySource = decodeUtf8(recoveryBytes);
            var storedVersion = GM_getValue(LAST_VERSION_KEY, '');
            var storedHash = GM_getValue(LAST_HASH_KEY, '');
            var storedRecoveryVersion = GM_getValue(LAST_RECOVERY_VERSION_KEY, '');
            var storedRecoveryHash = GM_getValue(LAST_RECOVERY_HASH_KEY, '');
            var releaseChanged = activeHash && storedHash && storedHash !== manifest.git_blob_sha;
            var recoveryChanged = activeRecoveryHash && storedRecoveryHash && storedRecoveryHash !== manifest.recovery_git_blob_sha;

            if (releaseChanged || recoveryChanged) {
                console.log('[PASI Loader] Verified PASI release change detected; refreshing the page before activation.', {
                    controller_changed: Boolean(releaseChanged),
                    recovery_changed: Boolean(recoveryChanged)
                });
                rememberManifest(manifest);
                window.location.reload();
                return;
            }

            rememberManifest(manifest);
            window[ACTIVE_HASH_PROPERTY] = manifest.git_blob_sha.toLowerCase();
            console.log('[PASI Loader] Verified controller release ' + manifest.version + '; activating.');
            eval(injectActiveOperationGetter(source));
            eval(recoverySource);
            window[ACTIVE_RECOVERY_HASH_PROPERTY] = manifest.recovery_git_blob_sha.toLowerCase();

            if (
                storedVersion === manifest.version &&
                storedHash === manifest.git_blob_sha &&
                storedRecoveryVersion === manifest.recovery_version &&
                storedRecoveryHash === manifest.recovery_git_blob_sha
            ) {
                console.log('[PASI Loader] Verified controller and recovery releases are current.');
            }
        } catch (error) {
            console.warn('[PASI Loader] Controller synchronization check failed:', error);
        }
    }

    async function checkForPublishedController() {
        try {
            var manifest = await loadLocalManifest();
            if (!manifest || manifest.enabled !== true) return;
            validateManifest(manifest);

            var activeHash = window[ACTIVE_HASH_PROPERTY] || '';
            var activeRecoveryHash = window[ACTIVE_RECOVERY_HASH_PROPERTY] || '';
            if (
                activeHash &&
                activeHash.toLowerCase() === manifest.git_blob_sha.toLowerCase() &&
                activeRecoveryHash &&
                activeRecoveryHash.toLowerCase() === manifest.recovery_git_blob_sha.toLowerCase()
            ) return;

            var sourceBytes = await requestBytes(LOCAL_SOURCE_URL, { 'Accept': 'application/octet-stream, text/plain, */*' });
            var blobSha = await gitBlobSha1Bytes(sourceBytes);
            console.log('[PASI Loader] Published controller received Git blob SHA: ' + blobSha);
            if (blobSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local controller Git blob mismatch; refusing to reload.', {
                    expected: manifest.git_blob_sha,
                    actual: blobSha
                });
                return;
            }

            var recoveryBytes = await requestBytes(LOCAL_RECOVERY_SOURCE_URL, { 'Accept': 'application/octet-stream, text/plain, */*' });
            var recoverySha = await gitBlobSha1Bytes(recoveryBytes);
            console.log('[PASI Loader] Published recovery received Git blob SHA: ' + recoverySha);
            if (recoverySha !== manifest.recovery_git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Local recovery Git blob mismatch; refusing to reload.', {
                    expected: manifest.recovery_git_blob_sha,
                    actual: recoverySha
                });
                return;
            }

            console.log('[PASI Loader] New verified PASI controller/recovery release detected; reloading page for clean activation.');
            rememberManifest(manifest);
            window.location.reload();
        } catch (error) {
            console.warn('[PASI Loader] Controller update check failed:', error);
        }
    }

    function rememberManifest(manifest) {
        GM_setValue(LAST_VERSION_KEY, manifest.version);
        GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
        GM_setValue(LAST_RECOVERY_VERSION_KEY, manifest.recovery_version);
        GM_setValue(LAST_RECOVERY_HASH_KEY, manifest.recovery_git_blob_sha);
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
        if (source.indexOf(needle) === -1) {
            throw new Error('Controller source did not expose the expected active-operation binding.');
        }
        return source.replace(needle, replacement);
    }

    async function gitBlobSha1Bytes(bytes) {
        var header = new TextEncoder().encode('blob ' + bytes.byteLength + '\0');
        var combined = new Uint8Array(header.byteLength + bytes.byteLength);
        combined.set(header, 0);
        combined.set(bytes, header.byteLength);

        var digest = await crypto.subtle.digest('SHA-1', combined);
        var digestBytes = new Uint8Array(digest);
        var output = '';
        for (var i = 0; i < digestBytes.length; i += 1) {
            output += digestBytes[i].toString(16).padStart(2, '0');
        }
        return output;
    }
})();
