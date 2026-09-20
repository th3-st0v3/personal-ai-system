const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('automation/chromium/pasi-chatgpt/content.js', 'utf8');

function buildMessageText(sourceText) {
  const start = sourceText.indexOf('function messageText(node)');
  const end = sourceText.indexOf('  function newestUserMatches', start);
  assert.ok(start >= 0 && end > start);
  return new Function(
    sourceText.slice(start, end) + '\nreturn messageText;'
  )();
}

test('native response extraction survives the line-collapse mutation', () => {
  const fixture = [
    'PASI_RESULT_STATUS: complete',
    'PASI_RESULT_PATCH_BEGIN',
    'diff --git a/example.txt b/example.txt',
    '--- a/example.txt',
    '+++ b/example.txt',
    '@@ -1 +1 @@',
    '-old',
    '+new',
    'PASI_RESULT_PATCH_END'
  ].join('\n');
  const node = { innerText: fixture, textContent: fixture };

  const current = buildMessageText(source);
  assert.equal(current(node), fixture);

  const collapsed = source
    .replace(
      ".replace(/\\r\\n?/g, '\\n')\n      .replace(/[ \\t]+(?=\\n)/g, '')",
      ".replace(/\\s+/g, ' ')"
    );
  const mutated = buildMessageText(collapsed);
  assert.notEqual(mutated(node), fixture);
  assert.doesNotMatch(mutated(node), /@@ -1 \\+1 @@\\n-old/);
});
