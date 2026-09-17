const fs = require('node:fs');
const test = require('node:test');
const assert = require('node:assert/strict');

const source = fs.readFileSync(
  'automation/tampermonkey/chatgpt-controller-loader.user.js',
  'utf8',
);

test('loader conditionally activates published controller releases', () => {
  assert.match(source, /controller-sync\.json/);
  assert.match(source, /manifest\.enabled !== true/);
  assert.match(source, /gitBlobSha1/);
  assert.match(source, /Controller Git blob mismatch/);
  assert.match(source, /eval\(source\)/);
  assert.match(source, /GM_getValue\(LAST_VERSION_KEY/);
  assert.match(source, /GM_setValue\(LAST_HASH_KEY/);
});

test('loader uses a resilient GitHub source path and API fallback', () => {
  assert.match(source, /raw\.githubusercontent\.com\/th3-st0v3\/personal-ai-system\/refs\/heads\/main/);
  assert.match(source, /api\.github\.com\/repos\/th3-st0v3\/personal-ai-system\/contents/);
  assert.match(source, /Primary GitHub file URL returned 404/);
  assert.match(source, /using GitHub API fallback/);
  assert.match(source, /decodeBase64Utf8/);
  assert.match(source, /X-GitHub-Api-Version/);
});

test('loader restricts controller source to PASI main', () => {
  assert.match(
    source,
    /TRUSTED_SOURCE_PREFIX = 'https:\/\/raw\.githubusercontent\.com\/th3-st0v3\/personal-ai-system\/'/,
  );
  assert.match(source, /TRUSTED_SOURCE_REF = '\/refs\/heads\/main\/'/);
});

test('loader computes the Git blob identity from UTF-8 bytes', () => {
  assert.match(source, /blob ' \+ data\.byteLength \+ '\\0'/);
  assert.match(source, /crypto\.subtle\.digest\('SHA-1'/);
});

test('loader polls slowly enough to keep API fallback within unauthenticated rate limits', () => {
  assert.match(source, /POLL_INTERVAL_MS = 5 \* 60 \* 1000/);
});
