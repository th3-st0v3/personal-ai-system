// ==UserScript==
// @name         Personal AI System - ChatGPT Controller Loader
// @namespace    https://github.com/th3-st0v3/personal-ai-system
// @version      1.2.0
// @description  Conditionally loads a verified PASI ChatGPT controller release from the trusted main branch.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      raw.githubusercontent.com
// @connect      api.github.com
// ==/UserScript==

(function () {
    'use strict';

    var MANIFEST_RAW_URL = 'https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/refs/heads/main/automation/tampermonkey/controller-sync.json';
    var GITHUB_API_FILE_PREFIX = 'https://api.github.com/repos/th3-st0v3/personal-ai-system/contents/';
    var TRUSTED_SOURCE_PREFIX = 'https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/';
    var TRUSTED_SOURCE_REF = '/refs/heads/main/';
    var POLL_INTERVAL_MS = 5 * 60 * 1000;
    var CHECK_TIMEOUT_MS = 10000;
    var LAST_VERSION_KEY = 'pasi_controller_synced_version';
    var LAST_HASH_KEY = 'pasi_controller_synced_git_blob_sha';

    console.log('[PASI Loader] Conditional controller loader active.');
    checkForPublishedController();
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

    async function requestWithFallback(primaryUrl, fallbackUrl, headers) {
        try {
            return await requestText(primaryUrl, headers);
        } catch (error) {
            if (error && error.status === 404 && fallbackUrl) {
                console.warn('[PASI Loader] Primary GitHub file URL returned 404; using GitHub API fallback.');
                return await requestText(fallbackUrl, {
                    'Accept': 'application/vnd.github+json',
                    'X-GitHub-Api-Version': '2026-03-10'
                });
            }
            throw error;
        }
    }

    async function requestGitHubApiFile(path) {
        var url = GITHUB_API_FILE_PREFIX + path.split('/').map(encodeURIComponent).join('/') + '?ref=main';
        var raw = await requestText(url, {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2026-03-10'
        });
        var payload = JSON.parse(raw);
        if (!payload || payload.encoding !== 'base64' || typeof payload.content !== 'string') {
            throw new Error('GitHub API did not return base64 file content.');
        }
        return decodeBase64Utf8(payload.content);
    }

    async function loadManifest() {
        var apiUrl = GITHUB_API_FILE_PREFIX + 'automation/tampermonkey/controller-sync.json?ref=main';
        try {
            var rawManifest = await requestText(MANIFEST_RAW_URL, {
                'Accept': 'application/json, text/plain, */*'
            });
            return JSON.parse(rawManifest);
        } catch (error) {
            if (!(error && error.status === 404)) throw error;
            console.warn('[PASI Loader] Manifest raw URL returned 404; using GitHub API fallback.');
            var apiManifest = await requestText(apiUrl, {
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2026-03-10'
            });
            var payload = JSON.parse(apiManifest);
            if (!payload || payload.encoding !== 'base64' || typeof payload.content !== 'string') {
                throw new Error('GitHub API did not return the controller sync manifest.');
            }
            return JSON.parse(decodeBase64Utf8(payload.content));
        }
    }

    async function checkForPublishedController() {
        try {
            var manifest = await loadManifest();
            if (!manifest || manifest.enabled !== true) return;
            if (!isValidManifest(manifest)) {
                console.error('[PASI Loader] Invalid controller sync manifest.');
                return;
            }

            var installedVersion = GM_getValue(LAST_VERSION_KEY, '');
            var installedHash = GM_getValue(LAST_HASH_KEY, '');
            if (installedVersion === manifest.version && installedHash === manifest.git_blob_sha) return;

            var source = await loadControllerSource(manifest.source_url);
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

    async function loadControllerSource(sourceUrl) {
        if (typeof sourceUrl !== 'string' || sourceUrl.indexOf(TRUSTED_SOURCE_PREFIX) !== 0) {
            throw new Error('Controller source URL is outside the trusted PASI namespace.');
        }
        try {
            return await requestText(sourceUrl, {
                'Accept': 'text/plain, */*'
            });
        } catch (error) {
            if (!(error && error.status === 404)) throw error;
            var relativePath = sourceUrl.slice((TRUSTED_SOURCE_PREFIX + 'refs/heads/main/').length);
            if (!relativePath || sourceUrl.indexOf(TRUSTED_SOURCE_REF) === -1) {
                throw error;
            }
            console.warn('[PASI Loader] Controller raw URL returned 404; using GitHub API fallback.');
            return await requestGitHubApiFile(relativePath);
        }
    }

    function isValidManifest(manifest) {
        return typeof manifest.version === 'string' &&
            /^\d+\.\d+\.\d+$/.test(manifest.version) &&
            typeof manifest.source_url === 'string' &&
            manifest.source_url.indexOf(TRUSTED_SOURCE_PREFIX) === 0 &&
            manifest.source_url.indexOf(TRUSTED_SOURCE_REF) !== -1 &&
            typeof manifest.git_blob_sha === 'string' &&
            /^[a-f0-9]{40}$/i.test(manifest.git_blob_sha);
    }

    function decodeBase64Utf8(value) {
        var binary = atob(String(value || '').replace(/\s+/g, ''));
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        return new TextDecoder().decode(bytes);
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
