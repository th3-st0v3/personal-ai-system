const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync(
  'automation/tampermonkey/chatgpt-controller-loader.user.js',
  'utf8',
);

test('loader activates only a verified local PASI controller release', () => {
  assert.match(source, /controller\/manifest/);
  assert.match(source, /controller\/source/);
  assert.match(source, /recovery\/source/);
  assert.match(source, /manifest\.enabled !== true/);
  assert.match(source, /gitBlobSha1/);
  assert.match(source, /Local controller Git blob mismatch/);
  assert.match(source, /Local recovery Git blob mismatch/);
  assert.match(source, /eval\(injectActiveOperationGetter\(source\)\)/);
  assert.match(source, /eval\(recoverySource\)/);
  assert.match(source, /GM_getValue\(LAST_VERSION_KEY/);
  assert.match(source, /GM_setValue\(LAST_HASH_KEY/);
});

test('loader uses localhost only for private-repository distribution', () => {
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/controller\/manifest/);
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/controller\/source/);
  assert.match(source, /http:\/\/127\.0\.0\.1:8766\/recovery\/source/);
  assert.doesNotMatch(source, /raw\.githubusercontent\.com/);
  assert.doesNotMatch(source, /api\.github\.com/);
});

test('loader reloads when either controller or recovery release changes', () => {
  assert.match(source, /ACTIVE_HASH_PROPERTY/);
  assert.match(source, /ACTIVE_RECOVERY_HASH_PROPERTY/);
  assert.match(source, /LAST_RECOVERY_HASH_KEY/);
  assert.match(source, /recoveryChanged/);
  assert.match(source, /Verified PASI release change detected; refreshing the page/);
  assert.match(source, /New verified PASI controller\/recovery release detected; reloading page/);
  assert.match(source, /window\.location\.reload\(\)/);
});

test('loader injects an active-operation getter without exposing credentials', () => {
  assert.match(source, /__PASI_CHATGPT_ACTIVE_OPERATION__/);
  assert.match(source, /activeOperationId/);
  assert.doesNotMatch(source, /document\.cookie/);
  assert.doesNotMatch(source, /localStorage\.getItem\(['"]password/);
});

test('loader computes the Git blob identity from UTF-8 bytes', () => {
  assert.match(source, /blob ' \+ data\.byteLength \+ '\\0'/);
  assert.match(source, /crypto\.subtle\.digest\('SHA-1'/);
});

test('loader polls quickly enough to activate after local service startup', () => {
  assert.match(source, /POLL_INTERVAL_MS = 30000/);
});
