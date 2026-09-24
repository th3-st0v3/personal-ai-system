const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const { JSDOM } = require('jsdom');

const CONTENT = fs.readFileSync('automation/chromium/pasi-chatgpt/content.js', 'utf8');
const DETECTORS = fs.readFileSync('automation/chromium/pasi-chatgpt/detectors.js', 'utf8');

function loadController(html, { mutateWhitespace = false } = {}) {
  const dom = new JSDOM(html, {
    url: 'https://chatgpt.com/c/test-fixture',
    pretendToBeVisual: true,
    runScripts: 'outside-only'
  });
  const visibleRects = () => [{ x: 0, y: 0, width: 1, height: 1 }];
  dom.window.HTMLElement.prototype.getClientRects = visibleRects;
  dom.window.SVGElement.prototype.getClientRects = visibleRects;
  dom.window.PASI_NATIVE_TEST_HOOKS = true;
  dom.window.PASI_TIMEOUT_POLICY = { get: () => ({}), defaults: {} };
  dom.window.chrome = {
    runtime: {
      sendMessage(_message, callback) {
        callback({ ok: false, status: 503, text: '{}', error: 'fixture' });
      },
      lastError: null
    }
  };
  dom.window.eval(DETECTORS);
  let source = CONTENT;
  if (mutateWhitespace) {
    const extractBlock = [
      "      const text = String(markdown[i].innerText || markdown[i].textContent || '')",
      "        .replace(/\\r\\n?/g, '\\n')",
      "        .replace(/[ \\t]+(?=\\n)/g, '')"
    ].join("\n");
    assert.ok(source.includes(extractBlock), 'whitespace-collapse mutation target is missing');
    source = source.replace(
      extractBlock,
      [
        "      const text = String(markdown[i].innerText || markdown[i].textContent || '')",
        "        .replace(/\\s+/g, ' ')"
      ].join("\n")
    );
  }
  dom.window.eval(source);
  assert.ok(dom.window.PASI_NATIVE_TEST_API);
  return dom;
}

test('native DOM fixture preserves multiline assistant response exactly', () => {
  const dom = loadController(
    '<main><div data-message-author-role="assistant"><div class="markdown">PASI_RESULT_STATUS: complete\nPASI_RESULT_PATCH_BEGIN\ndiff --git a/example.txt b/example.txt\n@@ -1 +1 @@\n-old\n+new\nPASI_RESULT_PATCH_END</div></div></main>'
  );
  const assistant = dom.window.document.querySelector('[data-message-author-role="assistant"]');
  const expected = [
    'PASI_RESULT_STATUS: complete',
    'PASI_RESULT_PATCH_BEGIN',
    'diff --git a/example.txt b/example.txt',
    '@@ -1 +1 @@',
    '-old',
    '+new',
    'PASI_RESULT_PATCH_END'
  ].join('\n');
  assert.equal(dom.window.PASI_NATIVE_TEST_API.extractAssistant(assistant), expected);
  dom.window.close();
});

test('native fingerprint collapses whitespace without altering extraction', () => {
  const dom = loadController('<div data-message-author-role="assistant"><div class="markdown">line one\nline two</div></div>');
  const api = dom.window.PASI_NATIVE_TEST_API;
  const assistant = dom.window.document.querySelector('[data-message-author-role="assistant"]');
  assert.equal(api.extractAssistant(assistant), 'line one\nline two');
  assert.equal(api.fingerprint(), 'line one line two');
  dom.window.close();
});

test('scoped detector ignores hostile phrases in messages and navigation', () => {
  const dom = loadController(
    '<nav><a href="#">New Chat — captcha context limit rate limit</a></nav><aside>Cloudflare verification and session has expired</aside><div data-message-author-role="assistant">Explain why a context limit message may mention captcha.</div>'
  );
  const before = dom.window.PASI_NATIVE_TEST_API.detectorState();
  assert.equal(before.auth_required, false);
  assert.equal(before.usage_limited, false);
  assert.equal(before.context_exhausted, false);

  const alert = dom.window.document.createElement('div');
  alert.setAttribute('role', 'alert');
  alert.textContent = 'Please complete the captcha security check';
  dom.window.document.body.append(alert);

  const after = dom.window.PASI_NATIVE_TEST_API.detectorState();
  assert.equal(after.auth_required, true);
  dom.window.close();
});

test('new-chat fixture ignores sidebar links and selects exact button', () => {
  const dom = loadController('<nav><a href="/c/old">New Chat</a></nav><main><button data-testid="new-chat-button" type="button">New chat</button></main>');
  const selected = dom.window.PASI_NATIVE_TEST_API.findNewChatControl();
  assert.equal(selected?.getAttribute('data-testid'), 'new-chat-button');
  dom.window.close();
});

test('operation prompt carries the operation nonce', () => {
  const dom = loadController('<main></main>');
  assert.equal(
    dom.window.PASI_NATIVE_TEST_API.operationPrompt({ operation_id: 'op-123', prompt: 'Do the task' }),
    '[PASI_OPERATION op-123]\nDo the task'
  );
  dom.window.close();
});

test('native response evidence rejects pre-prompt assistant messages and accepts only a new reply after the operation prompt', () => {
  const dom = loadController(
    '<main>' +
      '<div data-message-author-role="assistant"><div class="markdown">old assistant response</div></div>' +
      '<div data-message-author-role="user"><div>[PASI_OPERATION op-123]\nDo the task</div></div>' +
      '</main>'
  );
  const api = dom.window.PASI_NATIVE_TEST_API;
  const snapshot = api.snapshotAssistantMessages();

  assert.equal(
    api.assistantResponseEvidence(snapshot, '[PASI_OPERATION op-123]\nDo the task', 'older baseline'),
    ''
  );

  const reply = dom.window.document.createElement('div');
  reply.setAttribute('data-message-author-role', 'assistant');
  reply.innerHTML = '<div class="markdown">new assistant response</div>';
  dom.window.document.querySelector('main').append(reply);

  assert.equal(
    api.assistantResponseEvidence(snapshot, '[PASI_OPERATION op-123]\nDo the task', 'older baseline'),
    'new assistant response'
  );
  dom.window.close();

  const reused = loadController(
    '<main>' +
      '<div id="assistant" data-message-author-role="assistant"><div class="markdown">old assistant response</div></div>' +
      '<div data-message-author-role="user"><div>[PASI_OPERATION op-456]\nDo the task</div></div>' +
      '</main>'
  );
  const reusedApi = reused.window.PASI_NATIVE_TEST_API;
  const reusedAssistant = reused.window.document.querySelector('#assistant');
  const reusedSnapshot = reusedApi.snapshotAssistantMessages();
  reusedAssistant.querySelector('.markdown').textContent = 'new assistant response';
  reused.window.document.querySelector('main').append(reusedAssistant);
  assert.equal(
    reusedApi.assistantResponseEvidence(
      reusedSnapshot,
      '[PASI_OPERATION op-456]\nDo the task',
      'old assistant response'
    ),
    'new assistant response'
  );
  reused.window.close();
});

test('whitespace-collapse mutation fails the multiline extraction contract', () => {
  const fixture = '<div data-message-author-role="assistant"><div class="markdown">line one\nline two</div></div>';
  const current = loadController(fixture);
  const mutated = loadController(fixture, { mutateWhitespace: true });
  const assistantCurrent = current.window.document.querySelector('[data-message-author-role="assistant"]');
  const assistantMutated = mutated.window.document.querySelector('[data-message-author-role="assistant"]');
  assert.equal(current.window.PASI_NATIVE_TEST_API.extractAssistant(assistantCurrent), 'line one\nline two');
  assert.equal(mutated.window.PASI_NATIVE_TEST_API.extractAssistant(assistantMutated), 'line one line two');
  assert.notEqual(
    mutated.window.PASI_NATIVE_TEST_API.extractAssistant(assistantMutated),
    current.window.PASI_NATIVE_TEST_API.extractAssistant(assistantCurrent)
  );
  current.window.close();
  mutated.window.close();
});


test('native submission falls through from a no-op form submit to a real send without duplicating the prompt', async () => {
  const dom = loadController(
    '<main>' +
      '<button aria-label="Thinking" aria-pressed="true">Thinking</button>' +
      '<form id="composer-form">' +
        '<textarea id="prompt-textarea"></textarea>' +
        '<button data-testid="send-button" type="submit">Send</button>' +
      '</form>' +
    '</main>'
  );
  const api = dom.window.PASI_NATIVE_TEST_API;
  const form = dom.window.document.querySelector('#composer-form');
  const button = dom.window.document.querySelector('[data-testid="send-button"]');
  form.requestSubmit = () => {};
  button.addEventListener('click', (event) => {
    event.preventDefault();
    const user = dom.window.document.createElement('div');
    user.setAttribute('data-message-author-role', 'user');
    user.textContent = '[PASI_OPERATION op-fallback]\\nDo the task';
    dom.window.document.querySelector('main').append(user);
    const stop = dom.window.document.createElement('button');
    stop.setAttribute('data-testid', 'stop-button');
    stop.textContent = 'Stop generating';
    dom.window.document.querySelector('main').append(stop);
  });

  const result = await api.submitPrompt(
    '[PASI_OPERATION op-fallback]\\nDo the task',
    { fastPath: true }
  );
  assert.equal(result.via, 'verified');
  assert.equal(result.attempt, 2);
  assert.equal(result.verified, true);
  assert.equal(result.timing.user_messages_added, 1);
  assert.equal(dom.window.document.querySelectorAll('[data-message-author-role="user"]').length, 1);
  dom.window.close();
});
