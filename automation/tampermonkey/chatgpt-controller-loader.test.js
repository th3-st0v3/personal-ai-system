const fs = require('node:fs');
const test = require('node:test');
const assert = require('node:assert/strict');

const source = fs.readFileSync(
  'automation/tampermonkey/chatgpt-controller-loader.user.js',
  'utf8',
);

test('loader validates and gates published controller releases', () => {
  assert.match(source, /controller-sync\.json/);
  assert.match(source, /manifest\.enabled !== true/);
  assert.match(source, /sha256Hex/);
  assert.match(source, /Controller hash mismatch/);
  assert.match(source, /eval\(source\)/);
  assert.match(source, /GM_getValue\(LAST_VERSION_KEY/);
  assert.match(source, /GM_setValue\(LAST_HASH_KEY/);
});

test('loader restricts source to the PASI main raw GitHub path', () => {
  assert.match(
    source,
    /https:\/\/raw\.githubusercontent\.com\/th3-st0v3\/personal-ai-system\/main\//,
  );
});
