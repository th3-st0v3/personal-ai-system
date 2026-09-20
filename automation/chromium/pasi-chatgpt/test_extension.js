const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const content = fs.readFileSync(path.join(root, 'content.js'), 'utf8');
const activity = fs.readFileSync(path.join(root, 'activity.js'), 'utf8');
const recovery = fs.readFileSync(path.join(root, 'recovery.js'), 'utf8');
const detectors = fs.readFileSync(path.join(root, 'detectors.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

test('native controller and recovery companion have unique recovery declarations', () => {
  assert.equal((content.match(/const RECOVERY_KEY = 'pasi:chatgpt-recovery';/g) || []).length, 1);
  assert.equal((content.match(/const MAX_CONTEXT_AUTO_RECOVERIES = 1;/g) || []).length, 1);
  assert.equal((recovery.match(/function usageLimited\(\)/g) || []).length, 1);
});

test('shared detectors scope terminal state markers away from messages and sidebar content', () => {
  assert.deepEqual(manifest.content_scripts[0].js, ['activity.js', 'timeout-config.js', 'detectors.js', 'content.js', 'recovery.js']);
  assert.match(content, /globalThis\.PASIChatGPTDetectors\?\.detect/);
  assert.match(recovery, /globalThis\.PASIChatGPTDetectors\?\.detect/);
  assert.doesNotMatch(detectors, /document\.body\?\.innerText/);
  assert.match(content, /globalThis\.PASIChatGPTDetectors\?\.detect/);
  assert.match(recovery, /globalThis\.PASIChatGPTDetectors\?\.detect/);
  const alert = {
    innerText: 'Your request hit a rate limit.',
    textContent: 'Your request hit a rate limit.',
    closest: () => null
  };
  const message = {
    innerText: 'The docs mention rate limit and captcha as examples.',
    textContent: 'The docs mention rate limit and captcha as examples.',
    closest: (selector) => selector.includes('data-message-author-role') ? message : null
  };
  const nav = {
    innerText: 'captcha sign in to continue',
    textContent: 'captcha sign in to continue',
    closest: (selector) => selector.includes('data-message-author-role') && selector.includes('nav, aside') ? nav : null
  };
  const documentMock = {
    querySelectorAll(selector) {
      if (selector === '[role="alert"]') return [alert, message, nav];
      return [];
    }
  };
  const scope = {};
  const detectorFactory = new Function('document', 'globalThis', detectors + '\nreturn globalThis.PASIChatGPTDetectors;');
  const api = detectorFactory(documentMock, scope);
  const result = api.detect();
  assert.equal(result.usage_limited, true);
  assert.equal(result.auth_required, false);
  assert.equal(result.scope_count, 1);
});

test('native extension is Manifest V3 with least-privilege required permissions', () => {
  assert.equal(manifest.version, '1.1.1');
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.background.service_worker, 'background.js');
  assert.ok(manifest.permissions.includes('alarms'));
  assert.ok(manifest.permissions.includes('storage'));
  assert.ok(!manifest.permissions.includes('tabs'));
  assert.ok(manifest.host_permissions.includes('http://127.0.0.1:8765/*'));
  assert.ok(manifest.host_permissions.includes('https://chatgpt.com/*'));
  assert.ok(manifest.host_permissions.includes('https://www.chatgpt.com/*'));
  assert.deepEqual(manifest.content_scripts[0].js, ['activity.js', 'timeout-config.js', 'detectors.js', 'content.js', 'recovery.js']);
});

test('native controller reports roadmap completion and repository progress markers', () => {
  assert.match(content, /const CONTROLLER_VERSION = ['"]2\.4\.11['"]/);
  assert.match(content, /function completionProgress\(responseText\)/);
  assert.match(content, /PASI_RESULT_STATUS:/);
  assert.match(content, /PASI_RESULT_REPOSITORY_PROGRESS:/);
  assert.match(content, /PASI_RESULT_NEXT_TASK:/);
  assert.match(content, /completion_status: statusMatch/);
  assert.match(content, /repository_progress: progressMatch/);
  assert.match(content, /next_task: nextTaskMatch/);
});

test('native content controller uses extension messaging instead of page-side loopback fetch', () => {
  assert.match(content, /chrome\.runtime\.sendMessage/);
  assert.match(content, /type: 'pasi-bridge-request'/);
  assert.doesNotMatch(content, /fetch\(['"]?BRIDGE/);
  assert.doesNotMatch(content, /127\.0\.0\.1:8765/);
  assert.doesNotMatch(content, /GM_xmlhttpRequest|GM_getValue|GM_setValue/);
  assert.match(content, /new_chat/);
  assert.match(content, /select_reasoning/);
  assert.match(content, /attach_github/);
  assert.match(content, /operation\.operation_type/);
});

test('native controller reconciles completed interrupted operations before clearing restart state', () => {
  assert.match(content, /const operation = payload\?\.operation;/);
  assert.match(content, /if \(operation\.status === 'completed'\)/);
  assert.match(content, /typeof operation\.response_text === 'string'/);
  assert.match(content, /payload\?\.operation\?\.response_text_available === true/);
  assert.match(content, /Boolean\(responseText\.trim\(\)\)/);
  assert.match(content, /await finishOperation\(operationId, responseText, true\)/);
  assert.match(content, /readJsonStorage\(ACTIVE_KEY\)/);
});

test('native controller reports health and preserves interrupted-operation recovery', () => {
  assert.match(content, /chatgpt_health/);
  assert.match(content, /chatgpt_chat_changed/);
  assert.match(content, /conversation_signature/);
  assert.match(content, /localStorage/);
  assert.match(content, /browser page reloaded during operation/);
  assert.match(content, /CHAT_EXHAUSTED/);
  assert.match(content, /CHAT_USAGE_LIMITED/);
  assert.match(content, /const current = await bridge\(`\/operation\?operation_id=/);
  assert.match(content, /content\.js owns completion and retry mutation/);
});

test('native transient control activation clears stale focus before ChatGPT hides or replaces UI', () => {
  assert.match(content, /function freshChatSurface\(previousLocation, previousChat\)/);
  assert.match(content, /freshRootChat = freshChatSurface\(previousLocation, previousChat\)/);
  assert.match(content, /new chat control did not reach a verified fresh chat surface/);
  assert.match(content, /const focused = document\.activeElement;/);

  assert.match(content, /function accessibilityHidden\(element\)/);
  assert.match(content, /current\.getAttribute\?\.\('aria-hidden'\) === 'true'/);
  assert.match(content, /current\.hasAttribute\?\.\('inert'\)/);
  assert.match(content, /if \(!element \|\| accessibilityHidden\(element\)\) return false;/);
  assert.match(content, /function clearFocusBeforeActivation\(\)/);
  assert.match(content, /const active = document\.activeElement;/);
  assert.match(content, /try \{ active\.blur\(\); \} catch \(_\) \{\}/);
  assert.match(content, /function activateControl\(element\)/);
  assert.match(content, /clearFocusBeforeActivation\(\);\s*try \{\s*element\.click\(\);/);
  assert.match(content, /if \(!activateControl\(button\)\) throw new Error\('PASI_NATIVE: New chat control activation failed'\)/);
  assert.match(content, /function nativeMouseActivate\(element\) \{/);
  assert.match(content, /function controllerClaim\(\)/);
  const mouseActivation = content.slice(
    content.indexOf('function nativeMouseActivate(element)'),
    content.indexOf('async function submitPrompt(expected)')
  );
  assert.match(mouseActivation, /clearFocusBeforeActivation\(\);/);
  assert.doesNotMatch(mouseActivation, /element\.focus\(\);/);

  const accessibilityStart = content.indexOf('function accessibilityHidden(element)');
  const visibleStart = content.indexOf('  function visible(element)');
  assert.ok(accessibilityStart >= 0 && visibleStart > accessibilityStart);
  const accessibilitySource = content.slice(accessibilityStart, visibleStart);
  const accessibilityHidden = new Function(
    accessibilitySource + '\nreturn accessibilityHidden;'
  )();

  const ariaAncestor = {
    parentElement: null,
    getAttribute(name) { return name === 'aria-hidden' ? 'true' : null; },
    hasAttribute() { return false; }
  };
  const ariaChild = {
    parentElement: ariaAncestor,
    getAttribute() { return null; },
    hasAttribute() { return false; }
  };
  const inertAncestor = {
    parentElement: null,
    getAttribute() { return null; },
    hasAttribute(name) { return name === 'inert'; }
  };
  const inertChild = {
    parentElement: inertAncestor,
    getAttribute() { return null; },
    hasAttribute() { return false; }
  };
  assert.equal(accessibilityHidden(ariaChild), true);
  assert.equal(accessibilityHidden(inertChild), true);
  assert.equal(accessibilityHidden({ parentElement: null, getAttribute() { return null; }, hasAttribute() { return false; } }), false);

  const freshStart = content.indexOf('function freshChatSurface(previousLocation, previousChat)');
  const freshEnd = content.indexOf('  function contextExhausted()', freshStart);
  assert.ok(freshStart >= 0 && freshEnd > freshStart);
  const freshSource = content.slice(freshStart, freshEnd);
  const buildFresh = new Function(
    'location',
    'composer',
    'generating',
    'userMessages',
    'assistantMessages',
    freshSource + '\nreturn freshChatSurface;'
  );
  const freshRoot = buildFresh(
    { href: 'https://chatgpt.com/' },
    () => true,
    () => false,
    () => [],
    () => []
  );
  assert.equal(freshRoot('https://chatgpt.com/old', 'https://chatgpt.com/c/old'), true);
  const freshChatPath = buildFresh(
    { href: 'https://chatgpt.com/c/new' },
    () => true,
    () => false,
    () => [],
    () => []
  );
  assert.equal(
    freshChatPath('https://chatgpt.com/c/new', 'https://chatgpt.com/c/old'),
    false
  );

  let blurred = false;
  let clicked = false;
  const hiddenAncestor = {
    parentElement: null,
    getAttribute(name) { return name === 'aria-hidden' ? 'true' : null; },
    hasAttribute() { return false; }
  };
  const focusedAfterClick = {
    parentElement: hiddenAncestor,
    getAttribute() { return null; },
    hasAttribute() { return false; },
    blur() { blurred = true; }
  };
  const focusDocument = {
    activeElement: { blur() { blurred = true; } },
    body: {},
    documentElement: {}
  };
  const focusStart = content.indexOf('function clearFocusBeforeActivation()');
  const focusEnd = content.indexOf('  async function newChat()', focusStart);
  assert.ok(focusStart >= 0 && focusEnd > focusStart);
  const focusSource = content.slice(focusStart, focusEnd);
  const buildActivation = new Function(
    'document',
    'visible',
    'disabled',
    'accessibilityHidden',
    focusSource + '\nreturn { activateControl };'
  );
  const activation = buildActivation(
    focusDocument,
    () => true,
    () => false,
    (element) => {
      for (let current = element; current; current = current.parentElement) {
        if (current.getAttribute?.('aria-hidden') === 'true' || current.hasAttribute?.('inert')) return true;
      }
      return false;
    }
  );
  assert.equal(
    activation.activateControl({
      click() {
        clicked = true;
        focusDocument.activeElement = focusedAfterClick;
      }
    }),
    true
  );
  assert.equal(blurred, true);
  assert.equal(clicked, true);
});

test('native recovery persists a claimable operation id and retry context', () => {
  assert.match(content, /recovery_operation_id: operation\.operation_id/);
  assert.match(content, /body\.recovery_context = recoveryContext/);
  assert.match(content, /const value = state\?\.\[RECOVERY_OPERATION_KEY\] \|\| state\?\.\[RECOVERY_RESUME_OPERATION_KEY\] \|\| state\?\.operation_id/);
});

test('native context recovery uses the context-specific retry counter', () => {
  assert.match(content, /const contextRetryCount = Number\(operation\.retry_counts\?\.context \|\| 0\)/);
  assert.match(content, /contextRetryCount < MAX_CONTEXT_AUTO_RECOVERIES/);
  assert.match(content, /contextRetryCount >= MAX_CONTEXT_AUTO_RECOVERIES/);
  assert.doesNotMatch(content, /Number\(operation\.retry_count \|\| 0\).*MAX_CONTEXT_AUTO_RECOVERIES/);
});

test('native prompt paths call the defined composer setter', () => {
  assert.match(content, /setText\(box, expected\);/);
  assert.match(content, /setText\(box, promptText\);/);
  assert.doesNotMatch(content, /(^|[^\\w.])insertText\(box,/m);
});

test('native assistant extraction preserves machine-readable marker and diff line breaks', () => {
  assert.match(content, /replace\(\/\\r\\n\?\/g, '\\n'\)/);
  assert.match(content, /function collapseWhitespace\(value\)/);
  assert.match(content, /function messageText\(node\)/);
  assert.match(content, /function extractAssistant\(node\)/);

  const messageStart = content.indexOf('function messageText(node)');
  const messageEnd = content.indexOf('  function newestUserMatches', messageStart);
  assert.ok(messageStart >= 0 && messageEnd > messageStart);
  const messageSource = content.slice(messageStart, messageEnd);
  const messageText = new Function(messageSource + '\nreturn messageText;')();
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
  assert.equal(messageText(node), fixture);
  assert.match(messageText(node), /PASI_RESULT_PATCH_BEGIN\ndiff --git/);
  assert.match(messageText(node), /@@ -1 \+1 @@\n-old\n\+new/);

  const fingerprintStart = content.indexOf('function fingerprint()');
  const fingerprintEnd = content.indexOf('\n  async function waitForResponse', fingerprintStart);
  assert.ok(fingerprintStart >= 0 && fingerprintEnd > fingerprintStart);
  const fingerprintSource = content.slice(fingerprintStart, fingerprintEnd);
  assert.match(fingerprintSource, /collapseWhitespace\(latestAssistant\(\)\)/);
});

test('native prompt execution prevents duplicate sends and requires stable final output', () => {
  assert.match(content, /function operationPrompt\(operation\)/);
  assert.match(content, /PASI_OPERATION/);
  assert.match(content, /generating\(\) \|\| userMessages\(\)\.length > baselineUserCount/);
  assert.match(content, /prompt submission already appears to be in progress/);
  assert.match(content, /const RESPONSE_SETTLE_MS = 3500/);
  assert.match(content, /stableFingerprint/);
  assert.match(content, /stableSince/);
  assert.match(content, /Date\.now\(\) - stableSince >= RESPONSE_SETTLE_MS/);
  assert.match(content, /PASI_RESULT_STATUS/);
});

test('native new-chat selection excludes navigation and requires an empty target', () => {
  assert.match(content, /function findNewChatControl\(\)/);
  assert.match(content, /button\[data-testid="new-chat-button"\]/);
  assert.match(content, /button\[aria-label="New chat"\]/);
  assert.match(content, /nav, aside, \[role="navigation"\]/);
  assert.match(content, /emptySurface = Boolean\(composer\(\)/);
  assert.match(content, /currentChat !== previousChat && emptySurface/);
});

test('native controller elects one tab through a renewable lease', () => {
  assert.match(content, /type: 'pasi-controller-claim'/);
  assert.match(content, /await controllerClaim\(\)/);
  assert.match(background, /CONTROLLER_LEASE_KEY/);
  assert.match(background, /CONTROLLER_LEASE_MS = 10 \* 1000/);
  assert.match(background, /sender\?\.tab\?\.id/);
  assert.match(background, /current\.tabId === tabId/);
  assert.match(background, /renewedAt: now/);
});

test('native prompt submission uses stable model selection and fail-closed Thinking verification', () => {
  assert.match(content, /case 'prompt': \{/);
  assert.match(content, /await restoreRecoveryContext\(operation\.recovery_context\)/);
  assert.match(content, /await selectThinking\(\)/);
  assert.match(content, /reasoningMode = 'thinking'/);
  assert.match(content, /function selectionState\(element\)/);
  assert.match(content, /data-selected/);
  assert.match(content, /data-checked/);
  assert.match(content, /data-testid="modal-intelligence-menu"/);
  assert.match(content, /button\[role="radio"\]/);
  assert.match(content, /function findModelPill\(\)/);
  assert.match(content, /currentModelMode\(\) === 'thinking'/);
  assert.match(content, /Thinking state is ambiguous; refusing to toggle the control/);
  assert.match(content, /Thinking state is ambiguous; refusing to toggle the menu control/);
  assert.match(content, /await submitPrompt\(promptText\)/);
  assert.match(content, /var DOM_POLL_MS = 250;/);
  assert.match(content, /DOM_POLL_MS = TIMEOUT_POLICY\.domPollMs \|\| DOM_POLL_MS/);
});

test('native Thinking selection prefers the composer model pill and stable intelligence modal', () => {
  assert.match(content, /button\.__composer-pill/);
  assert.match(content, /\[data-testid="model-configure-modal"\]/);
  assert.match(content, /\[data-testid="modal-intelligence-menu"\]/);
  assert.match(content, /button\[role="radio"\]/);
});

test('native prompt submission re-checks auth, exhaustion, and Thinking at the send boundary', () => {
  assert.match(content, /const THINKING_VERIFY_MS = 5000;/);
  assert.match(content, /async function verifyThinkingState\(\)/);
  assert.match(content, /return waitFor\(\(\) => \{/);
  assert.match(content, /\}, THINKING_VERIFY_MS\)/);
  assert.match(content, /async function ensureThinkingReady\(\)/);
  assert.match(content, /if \(state === true\) \{/);
  assert.match(content, /state = await verifyThinkingState\(\)/);
  assert.match(content, /for \(let attempt = 1; attempt <= 2; attempt \+= 1\)/);
  assert.match(content, /await selectThinking\(\)/);
  assert.match(content, /if \(await verifyThinkingState\(\)\)/);
  assert.match(content, /if \(!\(await ensureThinkingReady\(\)\)\)/);
  assert.match(content, /PASI_NATIVE: Thinking state could not be verified before prompt submission/);
  assert.match(content, /function markThinkingUnavailable\(reason\)/);
  assert.match(content, /thinking_available: false/);
  assert.match(content, /reasoning_mode: 'unavailable'/);
  assert.match(content, /current ChatGPT account\/model does not expose a usable Thinking model option/);
  assert.match(content, /current ChatGPT menu does not expose a usable Thinking option/);
  assert.match(content, /if \(reasoningMode !== 'unavailable'\) reasoningMode = 'thinking';/);
  assert.match(content, /await ensurePromptSubmissionReady\(\);[\s\S]*const button = await waitForSend\(box\)/);
  assert.equal((content.match(/async function waitForSubmissionAck\(expected, baselineUserCount\)/g) || []).length, 1);
  assert.equal((content.match(/async function ensurePromptSubmissionReady\(\)/g) || []).length, 1);
  assert.equal((content.match(/function composerContainsPrompt\(element, expected\)/g) || []).length, 1);
});

test('native prompt submission requires explicit acknowledgement and composer-scoped send controls', () => {
  assert.match(content, /SUBMISSION_ACK_MS = 7500/);
  assert.match(content, /SUBMISSION_ATTEMPTS = 3/);
  assert.match(content, /newestUserMatches/);
  assert.match(content, /waitForSubmissionAck/);
  assert.match(content, /function sendCandidatesForComposer\(box\)/);
  assert.match(content, /button\[data-testid="send-button"\]/);
  assert.match(content, /button\[aria-label="Send prompt"\]/);
  assert.match(content, /button\[aria-label="Send message"\]/);
  assert.match(content, /Generic submit controls are safe only when owned by the exact composer/);
  assert.match(content, /few ancestors from the active composer/);
  assert.match(content, /function labeledSendInScope\(scope\)/);
  assert.match(content, /const form = box\?\.closest\?\.\('form'\) \|\| null/);
  assert.match(content, /return labeledSendInScope\(form \|\| box\?\.parentElement \|\| null\)/);
  assert.match(content, /waitForSend\(box\)/);
  assert.doesNotMatch(content, /const send = await waitForSend\(\)/);
  assert.match(content, /button\[data-testid\*="send" i\]/);
  assert.match(content, /button\[aria-label\*="send" i\]/);
  assert.match(content, /button\[title\*="send" i\]/);
  assert.match(content, /function nearbyScopedControls\(box\)/);
  assert.match(content, /unique.*generic submit buttons|multiple generic submit buttons/);
  assert.doesNotMatch(content, /if \(generating\(\) && userMessages\(\)\.length > baselineUserCount\) return true/);
  assert.match(content, /function composerContainsPrompt\(element, expected\)/);
  assert.match(content, /element\.focus\(\);/);
  assert.match(content, /const currentBox = composer\(\);/);
  assert.match(content, /const currentButton = sendCandidatesForComposer\(currentBox\)\[0\] \|\| button/);
  assert.match(content, /form\?\.requestSubmit/);
  assert.match(content, /const buttonType = String\(button\?\.getAttribute\?\.\('type'\) \|\| 'submit'\)/);
  assert.match(content, /if \(!button \|\| buttonType === 'submit'\) form\.requestSubmit\(button \|\| undefined\);/);
  assert.match(content, /else form\.requestSubmit\(\)/);
  assert.doesNotMatch(content, /form\.requestSubmit\(afterClick\)/);
  assert.doesNotMatch(content, /form\.requestSubmit\(afterClick\)/);
  assert.match(content, /function dispatchEnter\(element\)/);
  assert.match(content, /function nativeMouseActivate\(element\)/);
  assert.match(content, /form\.requestSubmit\(button \|\| undefined\)/);
  assert.match(content, /nativeMouseActivate\(currentButton\)/);
  assert.match(content, /dispatchEnter\(retryBox\)/);
  assert.doesNotMatch(content, /if \(!current \|\| !composerContainsPrompt\(current, expected\)\) \{\s*if \(generating\(\)\) return true;/);
  assert.match(content, /new KeyboardEvent\('keypress', init\)/);
  assert.match(content, /const retryBox = composer\(\);/);
  assert.match(content, /if \(retryBox && composerContainsPrompt\(retryBox, expected\) && !generating\(\)\)/);
  assert.match(content, /prompt submission could not be verified after bounded attempts/);
});

test('native completion persists response text before bounded acknowledgement retries', () => {
  assert.match(content, /response_text: responseText\.slice\(0, 50000\)/);
  assert.match(content, /\/chat\/finished/);
  assert.match(content, /response_text_available: typeof responseText === 'string' && Boolean\(responseText\.trim\(\)\)/);
  assert.match(content, /await reportObservation\('chatgpt_response'/);
  assert.match(content, /for \(let attempt = 1; attempt <= 3; attempt \+= 1\)/);
  assert.match(content, /\/operation\?operation_id=/);
  assert.match(content, /status === 'completed'/);
  assert.match(content, /response_text_available === true/);
  assert.match(content, /typeof payload\?\.operation\?\.response_text === 'string'/);
  assert.match(content, /Boolean\(payload\.operation\.response_text\.trim\(\)\)/);
});

test('native new-chat creation requires a changed conversation identity or genuinely empty chat', () => {
  assert.match(content, /previousChat = chatUrl\(\)/);
  assert.match(content, /differentChat/);
  assert.match(content, /initialChatReady/);
  assert.match(content, /new chat control did not change conversation identity/);
});

test('activity indicator reconciles stale browser state with terminal backend operations', () => {
  assert.match(activity, /async function backendOperation\(operationId\)/);
  assert.ok(activity.includes("path: '/operation?operation_id=' + encodeURIComponent(String(operationId))"));
  assert.match(activity, /\['completed', 'failed', 'cancelled'\]\.includes\(backend\.status\)/);
  assert.doesNotMatch(activity, /localStorage\.removeItem\(ACTIVE_KEY\)/);
  assert.match(activity, /The controller owns lifecycle cleanup/);
  assert.match(activity, /let syncInFlight = false/);
  assert.match(activity, /if \(syncInFlight\) return/);
});

test('activity indicator is isolated, non-interactive, and reduced-motion aware', () => {
  assert.match(activity, /pasi-activity-indicator/);
  assert.match(activity, /attachShadow\(\{ mode: 'closed' \}\)/);
  assert.match(activity, /pointer-events: none/);
  assert.match(activity, /prefers-reduced-motion: reduce/);
  assert.match(activity, /const state = isGenerating \? 'Thinking' : sawGeneration \? 'Finishing' : 'Working'/);
  assert.match(activity, /label\.textContent = `PASI · \$\{state\}`/);
  assert.match(activity, /const POLL_MS = 2000;/);
  assert.match(activity, /setInterval\(sync, POLL_MS\)/);
});

test('native restart recovery retries persisted response evidence before clearing active state', () => {
  assert.match(content, /if \(operation\.status === 'completed'\)/);
  assert.match(content, /const responseAvailable = Boolean\(responseText\.trim\(\)\)/);
  assert.match(content, /await finishOperation\(operationId, responseText, true\)/);
  assert.match(content, /const visibleResponse = latestAssistant\(\)/);
  assert.match(content, /await finishOperation\(operationId, visibleResponse, true\)/);
  assert.match(content, /localStorage\.removeItem\(ACTIVE_KEY\)/);
});

test('native recovery companion is observation-only', () => {
  assert.match(recovery, /recovery_action: 'observe_only'/);
  assert.match(recovery, /recovery_action: 'observe_response_only'/);
  assert.doesNotMatch(recovery, /location\.reload\(\)/);
  assert.doesNotMatch(recovery, /\/chat\/finished/);
  assert.doesNotMatch(recovery, /\/chat\/failed/);
  assert.doesNotMatch(recovery, /\/queue/);
  assert.doesNotMatch(recovery, /\/next-operation/);
  assert.match(content, /content\.js owns completion and retry mutation/);
});

test('operation lookup route is accepted by the MV3 service worker allowlist', () => {
  assert.ok(background.includes("const BRIDGE_OPERATION_RE = /^\\/operation\\?operation_id=[^&]{1,200}$/;"));
});

test('loopback bridge access is confined to the MV3 service worker', () => {
  assert.doesNotMatch(background, /targetAddressSpace/);
  assert.ok(background.includes("cache: 'no-store'"));
  assert.ok(!activity.includes("fetch(`http://127.0.0.1:8765"));
  assert.ok(!recovery.includes("fetch(BRIDGE"));
  assert.ok(background.includes("const BRIDGE_ROUTES = new Set(["));
  assert.ok(background.includes("function allowedBridgeRequest(method, path)"));
  assert.match(background, /BRIDGE_OPERATION_RE/);
  assert.match(background, /operation_id=/);
  assert.ok(background.includes("chrome.runtime.onMessage.addListener"));
  assert.ok(background.includes("message.type !== 'pasi-bridge-request'"));
  assert.ok(background.includes("https://chatgpt.com/"));
  assert.ok(background.includes("https://www.chatgpt.com/") || background.includes("www.chatgpt.com"));
  assert.ok(background.includes("allowedBridgeRequest(method, path)"));
  assert.ok(background.includes("bridgeFetch(path, method, body, 10000)"));
  assert.ok(manifest.host_permissions.includes("http://127.0.0.1:8765/*"));
  assert.ok(!content.includes("fetch(BRIDGE"));
  assert.ok(!content.includes("http://127.0.0.1:8765/operation"));
  assert.ok(!activity.includes("http://127.0.0.1:8765/operation"));
  assert.ok(!recovery.includes("fetch(BRIDGE"));
});

test('background service worker performs bounded stale-tab recovery', () => {
  assert.match(background, /chrome\.alarms\.create/);
  assert.match(background, /chrome\.tabs\.query/);
  assert.match(background, /chrome\.tabs\.reload/);
  assert.match(background, /MAX_REFRESHES/);
  assert.match(background, /auth_required/);
});

test('native controller defers first context-exhaustion failure to bounded recovery', () => {
  assert.match(content, /RECOVERY_KEY = 'pasi:chatgpt-recovery'/);
  assert.match(content, /MAX_CONTEXT_AUTO_RECOVERIES = 1/);
  assert.match(content, /errorMessage\.startsWith\('CHAT_EXHAUSTED:'\)/);
  assert.match(content, /rememberContextRecovery\(operation, error\)/);
  assert.match(content, /context recovery exhausted/);
  assert.match(content, /await reportObservation\('chatgpt_response'/);
});

test('background watchdog targets the tab matching the reported ChatGPT conversation before fallback recency', () => {
  assert.match(background, /const targetChatUrl = typeof health\.data\.chat_url === 'string'/);
  assert.match(background, /tabs\.find\(\(tab\) => tab\.url === targetChatUrl\)/);
  assert.match(background, /await reloadBoundedTab\(matchingTab\)/);
});

test('background bounded reload helper retains per-tab refresh budget', () => {
  assert.match(background, /async function reloadBoundedTab\(tab\)/);
  assert.match(background, /const budget = await refreshBudget\(tab\.id\)/);
  assert.match(background, /chrome\.storage\.local\.set/);
  assert.match(background, /chrome\.tabs\.reload\(tab\.id\)/);
});

test('native controller pauses ordinary queue polling while a recovery state is active', () => {
  assert.ok(
    /if \(processing \|\| activeOperationId !== null(?: \|\| extensionContextInvalidated)?\) return/.test(content)
  );
});

test('native recovery claims only the persisted recovery operation instead of consuming ordinary queue order', () => {
  assert.match(content, /const RECOVERY_OPERATION_KEY = 'recovery_operation_id'/);
  assert.match(content, /recoveryOperationId\(\)/);
  assert.match(content, /\/chat\/claim/);
  assert.match(content, /body: \{ operation_id: recoveryOperation \}/);
});

test('native prompt retries restore only the validated requested conversational context', () => {
  assert.match(content, /let githubRepository = null/);
  assert.match(content, /function recoveryContext\(\)/);
  assert.match(content, /async function restoreRecoveryContext\(context\)/);
  assert.match(content, /await restoreRecoveryContext\(operation\.recovery_context\)/);
  assert.match(content, /recovery_context: recoveryContext\(\)/);
  assert.match(content, /recovery GitHub context conflicts with the current attachment/);
});

test('native recovery exact-claims the original prompt retry and clears its resume marker on completion', () => {
  assert.match(content, /RECOVERY_RESUME_OPERATION_KEY = 'resume_operation_id'/);
  assert.match(content, /state\?\.\[RECOVERY_OPERATION_KEY\] \|\| state\?\.\[RECOVERY_RESUME_OPERATION_KEY\]/);
  assert.match(content, /function recoveryResumeOperationId\(\)/);
  assert.match(content, /localStorage\.removeItem\(RECOVERY_KEY\)/);
});

test('native restart reconciliation trusts nonblank persisted response text over stale availability flags', () => {
  assert.match(content, /const responseAvailable = Boolean\(responseText\.trim\(\)\);/);
  assert.doesNotMatch(content, /operation\.response_text_available === true &&\s+Boolean\(responseText\.trim\(\)\)/);
});

test('native prompt completion refuses an empty response payload while non-prompt operations may complete without one', () => {
  assert.match(content, /async function finishOperation\(operationId, responseText = '', requireResponseText = false\)/);
  assert.match(content, /if \(requireResponseText && \(typeof responseText !== 'string' \|\| !responseText\.trim\(\)\)\)/);
  assert.match(content, /await finishOperation\(operation\.operation_id, response, true\)/);
  assert.match(content, /await finishOperation\(operation\.operation_id\);/);
});

test('native prompt submission tolerates corrupt active recovery state', () => {
  assert.match(content, /function readJsonStorage\(key\)/);
  assert.match(content, /JSON\.parse\(localStorage\.getItem\(key\) \|\| 'null'\)/);
  assert.match(content, /catch \(_\) \{\s*return null;\s*\}/);
  assert.match(content, /const activeState = readJsonStorage\(ACTIVE_KEY\) \|\| \{\};/);
});

test('native response recovery keeps the pre-prompt baseline after a timeout', () => {
  assert.match(content, /const baseline = fingerprint\(\);/);
  assert.match(content, /localStorage\.setItem\(ACTIVE_KEY, JSON\.stringify\(\{ \.\.\.activeState, baseline \}\)\);/);
  assert.match(content, /baseline: typeof stored\?\.baseline === 'string' \? stored\.baseline : fingerprint\(\),/);
});

test('native controller preserves prompt operations for bounded response recovery', () => {
  assert.match(content, /function rememberResponseRecovery\(operation, error\)/);
  assert.match(content, /response_recovery: true/);
  assert.match(content, /phase: 'monitoring'/);
  assert.match(content, /errorMessage\.startsWith\('PASI_NATIVE: response text unavailable;'/);
  assert.match(content, /errorMessage\.startsWith\('PASI_NATIVE: ChatGPT generation timed out'/);
  assert.match(content, /const responseRecoveryEligible/);
  assert.match(content, /if \(responseRecoveryEligible\)/);
  assert.match(content, /rememberResponseRecovery\(operation, error\)/);
  assert.match(content, /finalized = false/);
});

test('background watchdog requires an active operation and exact chat identity before reloading', () => {
  assert.match(background, /if \(status\.queue_size <= 0 && !String\(health\.data\.active_operation_id \|\| ''\)\.trim\(\)\) return/);
  assert.match(background, /const targetChatUrl = typeof health\.data\.chat_url === 'string' \? health\.data\.chat_url\.trim\(\) : '';/);
  assert.match(background, /if \(!targetChatUrl\) return;/);
  assert.match(background, /if \(!matchingTab\) \{/);
  assert.match(background, /const CREATE_RETRY_MS = 60 \* 1000/);
  assert.match(background, /async function createCooldown\(targetChatUrl\)/);
  assert.match(background, /await markCreateAttempt\(targetChatUrl\)/);
  assert.match(background, /try \{\s*await chrome\.tabs\.create\(\{ url: targetChatUrl \}\);\s*\} catch/);
  assert.match(background, /Never substitute another ChatGPT tab/);
  assert.doesNotMatch(background, /tabs\.sort\(\(a, b\) => Number\(b\.lastAccessed/);
});

test('background watchdog recreates only the verified conversation when its tab is missing', () => {
  assert.match(background, /if \(!matchingTab\) \{/);
  assert.match(background, /await chrome\.tabs\.create\(\{ url: targetChatUrl \}\)/);
  assert.match(background, /Never substitute another ChatGPT tab/);
  assert.doesNotMatch(background, /tabs\.sort\(\(a, b\) => Number\(b\.lastAccessed/);
});

test('background watchdog rate-limits missing-tab recreation after browser creation failures', () => {
  assert.match(background, /const CREATE_RETRY_MS = 60 \* 1000/);
  assert.match(background, /const key = `create:\$\{targetChatUrl\}`/);
  assert.match(background, /if \(await createCooldown\(targetChatUrl\)\) return/);
  assert.match(background, /await markCreateAttempt\(targetChatUrl\)/);
  assert.match(background, /try \{\s*await chrome\.tabs\.create\(\{ url: targetChatUrl \}\);\s*\} catch \(_\)/);
});

test('background watchdog clears a stale creation cooldown after the exact tab is restored', () => {
  assert.match(background, /if \(!matchingTab\) \{/);
  assert.match(background, /await chrome\.storage\.local\.remove\(`create:\$\{targetChatUrl\}`\);/);
  assert.match(background, /await reloadBoundedTab\(matchingTab\)/);
});


test('native restart recovery uses the persisted pre-prompt baseline when terminal response text is missing', () => {
  assert.match(content, /else if \(!generating\(\)/);
  assert.match(content, /const baseline = typeof stored\?\.baseline === 'string' \? stored\.baseline : ''/);
  assert.match(content, /const visibleResponse = latestAssistant\(\)/);
  assert.match(content, /visibleFingerprint !== baseline/);
  assert.match(content, /await finishOperation\(operationId, visibleResponse, true\)/);
});
