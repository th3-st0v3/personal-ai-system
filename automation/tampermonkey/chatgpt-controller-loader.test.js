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

test('loader restricts controller source to PASI main', () => {
  assert.match(
    source,
    /https:\/\/raw\.githubusercontent\.com\/th3-st0v3\/personal-ai-system\/main\//,
  );
});

test('loader computes the Git blob identity from UTF-8 bytes', () => {
  assert.match(source, /blob ' \+ data\.byteLength \+ '\\0'/);
  assert.match(source, /crypto\.subtle\.digest\('SHA-1'/);
});
