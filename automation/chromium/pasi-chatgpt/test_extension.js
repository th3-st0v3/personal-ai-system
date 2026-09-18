const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const content = fs.readFileSync(path.join(root, 'content.js'), 'utf8');
const activity = fs.readFileSync(path.join(root, 'activity.js'), 'utf8');
const recovery = fs.readFileSync(path.join(root, 'recovery.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

test('native extension is Manifest V3 with least-privilege required permissions', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.background.service_worker, 'background.js');
  assert.ok(manifest.permissions.includes('alarms'));
  assert.ok(manifest.permissions.includes('storage'));
  assert.ok(!manifest.permissions.includes('tabs'));
  assert.ok(manifest.host_permissions.includes('http://127.0.0.1:8765/*'));
  assert.ok(manifest.host_permissions.includes('https://chatgpt.com/*'));
  assert.ok(manifest.host_permissions.includes('https://www.chatgpt.com/*'));
  assert.deepEqual(manifest.content_scripts[0].js, ['activity.js', 'content.js', 'recovery.js']);
});

test('native content controller uses standard fetch instead of GM APIs', () => {
  assert.match(content, /fetch\(BRIDGE/);
  assert.doesNotMatch(content, /GM_xmlhttpRequest|GM_getValue|GM_setValue/);
  assert.match(content, /new_chat/);
  assert.match(content, /select_reasoning/);
  assert.match(content, /attach_github/);
  assert.match(content, /operation\.operation_type/);
});

test('native controller reports health and preserves interrupted-operation recovery', () => {
  assert.match(content, /chatgpt_health/);
  assert.match(content, /chatgpt_chat_changed/);
  assert.match(content, /conversation_signature/);
  assert.match(content, /localStorage/);
  assert.match(recovery, /browser page reloaded during operation/);
  assert.match(content, /CHAT_EXHAUSTED/);
  assert.match(content, /CHAT_USAGE_LIMITED/);
  assert.match(content, /const current = await bridge\(`\/operation\?operation_id=/);
  assert.match(content, /Preserve non-terminal operations for the dedicated bounded recovery companion/);
});

test('native prompt submission requires explicit user-message acknowledgement', () => {
  assert.match(content, /SUBMISSION_ACK_MS = 2500/);
  assert.match(content, /SUBMISSION_ATTEMPTS = 3/);
  assert.match(content, /newestUserMatches/);
  assert.match(content, /waitForSubmissionAck/);
  assert.match(content, /prompt submission could not be verified after bounded attempts/);
});

test('native completion persists response text before bounded acknowledgement retries', () => {
  assert.match(content, /response_text: responseText\.slice\(0, 50000\)/);
  assert.match(content, /\/chat\/finished/);
  assert.match(content, /response_text_available: Boolean\(responseText\)/);
  assert.match(content, /await reportObservation\('chatgpt_response'/);
  assert.match(content, /for \(let attempt = 1; attempt <= 3; attempt \+= 1\)/);
  assert.match(content, /\/operation\?operation_id=/);
  assert.match(content, /status === 'completed'/);
});

test('native new-chat creation requires a changed conversation identity or genuinely empty chat', () => {
  assert.match(content, /previousChat = chatUrl\(\)/);
  assert.match(content, /differentChat/);
  assert.match(content, /initialChatReady/);
  assert.match(content, /new chat control did not change conversation identity/);
});

test('activity indicator is isolated, non-interactive, and reduced-motion aware', () => {
  assert.match(activity, /pasi-activity-indicator/);
  assert.match(activity, /attachShadow\(\{ mode: 'closed' \}\)/);
  assert.match(activity, /pointer-events: none/);
  assert.match(activity, /prefers-reduced-motion: reduce/);
  assert.match(activity, /const state = isGenerating \? 'Thinking' : sawGeneration \? 'Finishing' : 'Working'/);
  assert.match(activity, /label\.textContent = `PASI · \$\{state\}`/);
  assert.match(activity, /setInterval\(sync, POLL_MS\)/);
});

test('native recovery companion preserves response text without blocking completion acknowledgement', () => {
  assert.match(recovery, /GENERATION_TIMEOUT_MS = 25 \* 60 \* 1000/);
  assert.match(recovery, /RECOVERY_TRIGGER_MS = GENERATION_TIMEOUT_MS/);
  assert.match(recovery, /location\.reload\(\)/);
  assert.match(recovery, /function usageLimited\(\)/);
  assert.match(recovery, /function replacementReason\(\)/);
  assert.match(recovery, /phase: 'preserve_current_chat'/);
  assert.match(recovery, /no_verified_usage_or_context_exhaustion/);
  assert.match(recovery, /CHAT_RECOVERED_RETRY/);
  assert.match(recovery, /operation_type: 'new_chat'/);
  assert.match(recovery, /response_text: bounded/);
  assert.match(recovery, /void report\('chatgpt_response'/);
  assert.match(recovery, /current\.status === 'failed'/);
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
  assert.match(content, /if \(processing \|\| activeOperationId !== null\) return/);
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

test('native prompt completion refuses an empty response payload while non-prompt operations may complete without one', () => {
  assert.match(content, /async function finishOperation\(operationId, responseText = '', requireResponseText = false\)/);
  assert.match(content, /if \(requireResponseText && \(typeof responseText !== 'string' \|\| !responseText\.trim\(\)\)\)/);
  assert.match(content, /await finishOperation\(operation\.operation_id, response, true\)/);
  assert.match(content, /await finishOperation\(operation\.operation_id\);/);
});

test('native prompt submission tolerates corrupt active recovery state', () => {
  assert.match(content, /let activeState = \{\};/);
  assert.match(content, /try \{\s*activeState = JSON\.parse\(localStorage\.getItem\(ACTIVE_KEY\) \|\| '\{\}'\);/);
  assert.match(content, /catch \(_\) \{\}/);
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
