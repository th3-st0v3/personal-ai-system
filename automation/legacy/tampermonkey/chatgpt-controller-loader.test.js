const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync(
  'automation/legacy/tampermonkey/chatgpt-controller-loader.user.js',
  'utf8',
);

test('loader verifies an enabled local PASI controller release without dynamic execution', () => {
  assert.match(source, /controller\/manifest/);
  assert.match(source, /controller\/source/);
  assert.match(source, /recovery\/source/);
  assert.match(source, /manifest\.enabled !== true/);
  assert.match(source, /gitBlobSha1Bytes/);
  assert.match(source, /Controller integrity verification failed/);
  assert.match(source, /Recovery integrity verification failed/);
  assert.match(source, /GM_setValue\(LAST_VERSION_KEY/);
  assert.match(source, /GM_setValue\(LAST_HASH_KEY/);
  assert.match(source, /Runtime execution is handled by the dedicated PASI Controller userscript/);
  assert.doesNotMatch(source, /\beval\s*\(/);
});

test('loader uses localhost only for private-repository distribution', () => {
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/controller\/manifest/);
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/controller\/source/);
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/recovery\/source/);
  assert.doesNotMatch(source, /raw\.githubusercontent\.com/);
  assert.doesNotMatch(source, /api\.github\.com/);
});

test('loader records controller and recovery release changes without reloading or injecting code', () => {
  assert.match(source, /LAST_HASH_KEY/);
  assert.match(source, /LAST_RECOVERY_HASH_KEY/);
  assert.match(source, /recoveryChanged/);
  assert.match(source, /Verified PASI release change detected/);
  assert.doesNotMatch(source, /window\.location\.reload\(\)/);
  assert.doesNotMatch(source, /__PASI_CHATGPT_ACTIVE_OPERATION__/);
});

test('loader does not expose credentials while handling release verification', () => {
  assert.match(source, /GM_xmlhttpRequest/);
  assert.doesNotMatch(source, /document\.cookie/);
  assert.doesNotMatch(source, /localStorage\.getItem\(['\"]password/);
});

test('loader computes the Git blob identity from raw response bytes', () => {
  assert.match(source, /responseType: 'arraybuffer'/);
  assert.match(source, /new Uint8Array\(response\.response\)/);
  assert.match(source, /blob ' \+ bytes\.byteLength \+ '\\0'/);
  assert.match(source, /crypto\.subtle\.digest\('SHA-1'/);
});

test('loader polls quickly enough to verify after local service startup', () => {
  assert.match(source, /POLL_INTERVAL_MS = 30000/);
});
