// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.7.0
// @description  Verifies PASI ChatGPT controller and recovery releases from the local PASI runtime without dynamic code execution.
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

    console.log('[PASI Loader] Verification-only ChatGPT loader v1.7.0 active.');
    verifyPublishedRelease();
    setInterval(verifyPublishedRelease, POLL_INTERVAL_MS);

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
                    if (response.status < 200 || response.status >= 300) {
                        var error = new Error('HTTP ' + response.status);
                        error.status = response.status;
                        reject(error);
                        return;
                    }
                    if (!(response.response instanceof ArrayBuffer)) {
                        reject(new Error('Expected ArrayBuffer response.'));
                        return;
                    }
                    resolve(new Uint8Array(response.response));
                },
                onerror: function () { reject(new Error('request failed')); },
                ontimeout: function () { reject(new Error('request timed out')); }
            });
        });
    }

    function decodeUtf8(bytes) {
        return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    }

    async function requestJson(url) {
        return JSON.parse(decodeUtf8(await requestBytes(url, {
            'Accept': 'application/json, text/plain, */*'
        })));
    }

    async function verifyPublishedRelease() {
        try {
            var manifest = await requestJson(LOCAL_MANIFEST_URL);
            validateManifest(manifest);

            if (manifest.enabled !== true) {
                console.warn('[PASI Loader] Controller release is disabled.');
                return;
            }

            var controllerBytes = await requestBytes(LOCAL_SOURCE_URL, {
                'Accept': 'application/octet-stream, text/plain, */*'
            });
            var controllerSha = await gitBlobSha1Bytes(controllerBytes);

            if (controllerSha !== manifest.git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Controller integrity verification failed.', {
                    expected: manifest.git_blob_sha,
                    actual: controllerSha
                });
                return;
            }

            var recoveryBytes = await requestBytes(LOCAL_RECOVERY_SOURCE_URL, {
                'Accept': 'application/octet-stream, text/plain, */*'
            });
            var recoverySha = await gitBlobSha1Bytes(recoveryBytes);

            if (recoverySha !== manifest.recovery_git_blob_sha.toLowerCase()) {
                console.error('[PASI Loader] Recovery integrity verification failed.', {
                    expected: manifest.recovery_git_blob_sha,
                    actual: recoverySha
                });
                return;
            }

            var previousControllerSha = GM_getValue(LAST_HASH_KEY, '');
            var previousRecoverySha = GM_getValue(LAST_RECOVERY_HASH_KEY, '');
            var controllerChanged = Boolean(previousControllerSha && previousControllerSha !== manifest.git_blob_sha);
            var recoveryChanged = Boolean(previousRecoverySha && previousRecoverySha !== manifest.recovery_git_blob_sha);

            GM_setValue(LAST_VERSION_KEY, manifest.version);
            GM_setValue(LAST_HASH_KEY, manifest.git_blob_sha);
            GM_setValue(LAST_RECOVERY_VERSION_KEY, manifest.recovery_version);
            GM_setValue(LAST_RECOVERY_HASH_KEY, manifest.recovery_git_blob_sha);

            if (controllerChanged || recoveryChanged) {
                console.log('[PASI Loader] Verified PASI release change detected.', {
                    controller_changed: controllerChanged,
                    recovery_changed: recoveryChanged,
                    controller_version: manifest.version,
                    recovery_version: manifest.recovery_version
                });
            } else {
                console.log('[PASI Loader] Verified controller ' + manifest.version + ' and recovery ' + manifest.recovery_version + '.');
            }

            console.log('[PASI Loader] Runtime execution is handled by the dedicated PASI Controller userscript; no eval is used.');
        } catch (error) {
            console.warn('[PASI Loader] Release verification failed:', error);
        }
    }

    function validateManifest(manifest) {
        if (!manifest || typeof manifest !== 'object') {
            throw new Error('Invalid controller manifest.');
        }
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
