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


test('native bridge caches the token and refreshes once after unauthorized responses', () => {
  assert.match(background, /let cachedBridgeToken = null/);
  assert.match(background, /let bridgeTokenPromise = null/);
  assert.match(background, /if \(!forceRefresh && cachedBridgeToken\) return cachedBridgeToken/);
  assert.match(background, /if \(response\.status === 401\)/);
  assert.match(background, /cachedBridgeToken = null/);
  assert.match(background, /token = await bridgeToken\(true\)/);
});

test('native extension packages and loads the shared timeout policy resource', () => {
  assert.deepEqual(manifest.web_accessible_resources, [{
    resources: ['timeout-policy.json'],
    matches: ['https://chatgpt.com/*', 'https://www.chatgpt.com/*']
  }]);
  const timeoutConfig = fs.readFileSync(path.join(root, 'timeout-config.js'), 'utf8');
  assert.match(timeoutConfig, /chrome\.runtime\.getURL\('timeout-policy\.json'\)/);
});

test('native background controller serializes concurrent lease claims', () => {
  assert.match(background, /CONTROLLER_LEASE_KEY/);
  assert.match(background, /CONTROLLER_LEASE_MS = 10 \* 1000/);
  assert.match(background, /let controllerClaimTail = Promise\.resolve\(\);/);
  assert.match(background, /function serializeControllerClaim\(task\)/);
  assert.match(background, /controllerClaimTail\.then\(task, task\)/);
  assert.match(background, /message\?\.type === 'pasi-controller-claim'/);
});

test('native background watchdog reacts to explicit connection failures even with a fresh observation', () => {
  assert.match(background, /const connectionFailure = health\.data\.connection_failure === true/);
  assert.match(background, /const observationStale = observationAge\(health\.observation\) > STALE_MS/);
  assert.match(background, /if \(!connectionFailure && !observationStale\) return;/);
  assert.match(background, /if \(!connectionFailure && !observationStale\) return;/);
  assert.match(background, /await reloadBoundedTab\(matchingTab\)/);
});

test('native recovery companion expires vanished operations after the bounded grace period', () => {
  assert.match(recovery, /MISSING_OPERATION_GRACE_MS = 60 \* 1000/);
  assert.match(recovery, /operation_missing_expired/);
  assert.match(recovery, /clearInterruptedState\(\)/);
  assert.match(recovery, /missing_operation_age_ms: age/);
});

test('native recovery companion uses the shared long-response timeout policy', () => {
  assert.match(recovery, /const GENERATION_TIMEOUT_MS = TIMEOUT_POLICY\.generationMs \|\| 60 \* 60 \* 1000/);
  assert.match(recovery, /const RECOVERY_TRIGGER_MS = TIMEOUT_POLICY\.recoveryTriggerMs \|\| GENERATION_TIMEOUT_MS/);
  assert.match(recovery, /recovery_trigger_ms: RECOVERY_TRIGGER_MS/);
});

test('native controller and recovery companion have unique recovery declarations', () => {
  assert.equal((content.match(/const RECOVERY_KEY = 'pasi:chatgpt-recovery';/g) || []).length, 1);
  assert.equal((content.match(/const MAX_CONTEXT_AUTO_RECOVERIES = 1;/g) || []).length, 1);
  assert.equal((recovery.match(/function usageLimited\(\)/g) || []).length, 1);
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
  assert.deepEqual(manifest.content_scripts[0].js, ['timeout-config.js', 'activity.js', 'recovery_progress.js', 'content.js', 'recovery.js']);
});

test('native controller keeps response telemetry off the completion critical path', () => {
  assert.match(content, /void reportObservation\('chatgpt_response'/);
  assert.ok(content.includes('}).catch(() => {});'));
  assert.doesNotMatch(content, /await reportObservation\('chatgpt_response'/);
});

test('native controller chains the next queued operation immediately after terminal completion', () => {
  assert.match(content, /let immediatePollQueued = false;/);
  assert.match(content, /function scheduleImmediatePoll\(\)/);
  assert.match(content, /queueMicrotask\(\(\) =>/);
  assert.match(content, /if \(finalized\) scheduleImmediatePoll\(\)/);
  assert.match(content, /void reportHealth\(\)/);
  assert.match(content, /const detail = errorMessage \+ ' \| ui=' \+ JSON\.stringify\(captureUiDiagnostics\(\)\)/);
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
  assert.match(content, /await finishOperation\(stored\.operation_id, responseText, true\)/);
  assert.match(content, /Keep the active marker so the next controller start can reconcile again/);
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

test('native prompt submission retains stable Thinking selectors while using best-effort selection', () => {
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
  assert.match(content, /await submitPrompt\(operation\.prompt\)/);
  assert.match(content, /const DOM_POLL_MS = TIMEOUT_POLICY\.domPollMs \|\| 20/);
  assert.match(content, /const PREVIOUS_RESPONSE_WAIT_MS = 5 \* 60 \* 1000;/);
  assert.match(content, /const GENERATION_START_WAIT_MS = 30 \* 1000;/);
});

test('native Thinking selection prefers the composer model pill and stable intelligence modal', () => {
  assert.match(content, /button\.__composer-pill/);
  assert.match(content, /\[data-testid="model-configure-modal"\]/);
  assert.match(content, /\[data-testid="modal-intelligence-menu"\]/);
  assert.match(content, /button\[role="radio"\]/);
});

test('native prompt submission uses best-effort Thinking and event-driven acknowledgement', () => {
  assert.match(content, /const MAX_RESPONSE_TEXT_CHARS = 120_000;/);
  assert.match(content, /const DOM_POLL_MS = TIMEOUT_POLICY\.domPollMs \|\| 20/);
  assert.match(content, /function waitUntil\(predicate, timeoutMs, pollMs = DOM_POLL_MS\)/);
  assert.match(content, /MutationObserver/);
  assert.match(content, /function snapshotUserMessages\(\)/);
  assert.match(content, /function promptFingerprints\(prompt\)/);
  assert.match(content, /function classifyNewUserMessages\(nodes, snapshot, head, tail, textOf\)/);
  assert.match(content, /async function ensureThinkingBestEffort\(\)/);
  assert.match(content, /await selectThinking\(\)/);
  assert.match(content, /reasoning_mode: 'unavailable'/);
  assert.match(content, /closeOpenMenus\(\)/);
  assert.doesNotMatch(content, /async function ensureThinkingReady\(\)/);
  assert.doesNotMatch(content, /async function verifyThinkingState\(\)/);
  assert.doesNotMatch(content, /async function waitForSubmissionAck\(expected, baselineUserCount\)/);
  assert.doesNotMatch(content, /newestUserMatches\(expected, baselineUserCount\)/);
  assert.match(content, /case 'select_reasoning': await ensureThinkingBestEffort\(\);/);
  assert.match(content, /await ensureThinkingBestEffort\(\)/);
  assert.match(content, /PASI_NATIVE: previous response still generating/);
  assert.match(content, /PASI_NATIVE: submission accepted but generation did not start/);
  assert.match(content, /clearMonitoringStateFor\(operation\.operation_id\)/);
});

test('native prompt submission uses a single send strategy and never duplicates a fired send', () => {
  assert.match(content, /const SUBMISSION_ACK_MS = TIMEOUT_POLICY\.submissionAckMs \|\| 1000/);
  assert.match(content, /const SUBMISSION_ATTEMPTS = 3/);
  assert.match(content, /const COMPLETION_RETRY_DELAY_MS = 20/);
  assert.match(content, /sleep\(COMPLETION_RETRY_DELAY_MS\)/);
  assert.match(content, /const snapshot = snapshotUserMessages\(\)/);
  assert.match(content, /const \{ head, tail \} = promptFingerprints\(expected\)/);
  assert.match(content, /state === 'match'/);
  assert.match(content, /state === 'new_unmatched' && generating\(\)/);
  assert.match(content, /const strategies = \[/);
  assert.match(content, /form\.requestSubmit\(button \|\| undefined\)/);
  assert.match(content, /nativeMouseActivate\(button\)/);
  assert.match(content, /dispatchEnter\(box\)/);
  assert.match(content, /const fired = await strategies\[attempt - 1\]\(readyBox, button\)/);
  assert.match(content, /Once a send strategy has fired, never/);
  assert.match(content, /const injectedAtMs = Date\.now\(\)/);
  assert.match(content, /injected_at_ms: injectedAtMs/);
  assert.match(content, /ack_at_ms: Date\.now\(\)/);
  assert.match(content, /user_messages_added: countNewUserMessages\(userMessages\(\), snapshot\)/);
  assert.match(content, /ack_verified: via === 'verified'/);
  assert.match(content, /submission_via: finalVia/);
  assert.match(content, /composer holds unrelated text; refusing to overwrite/);
  assert.doesNotMatch(content, /newestUserMatches/);
});

test('native completion captures responses through the event-driven waiter and bounded evidence', () => {
  assert.match(content, /async function waitForResponse\(baseline(?:,|\))/);
  assert.match(content, /let sawGeneration = false/);
  assert.match(content, /const response = await waitUntil\(\(\) =>/);
  assert.match(content, /const responseText = latestAssistant\(\)/);
  assert.match(content, /PASI_NATIVE: ChatGPT generation timed out/);
  assert.match(content, /const MAX_RESPONSE_TEXT_CHARS = 120_000;/);
  assert.match(content, /response_text: responseText\.slice\(0, MAX_RESPONSE_TEXT_CHARS\)/);
  assert.match(content, /browserTiming\.generation_start_ms = generationStartMs/);
  assert.match(content, /browserTiming\.completed_at_ms = Date\.now\(\)/);
  assert.match(content, /finishOperation\(operation\.operation_id, response, true, browserTiming\)/);
  assert.match(content, /\/chat\/finished/);
  assert.match(content, /response_text_available: typeof responseText === 'string' && Boolean\(responseText\.trim\(\)\)/);
  assert.match(content, /void reportObservation\('chatgpt_response'/);
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

test('native recovery retries completed prompt evidence before clearing the active marker', () => {
  assert.match(recovery, /if \(current\.status === 'completed' \|\| current\.status === 'failed' \|\| current\.status === 'cancelled'\) \{/);
  assert.match(recovery, /finishVisibleResponse\(operationId, current, ''\)/);
  assert.match(recovery, /else if \(current\.status !== 'completed'\)/);
  assert.match(recovery, /clearInterruptedState\(\)/);
});

test('native recovery companion preserves response text without blocking completion acknowledgement', () => {
  assert.match(recovery, /const GENERATION_TIMEOUT_MS = TIMEOUT_POLICY\.generationMs \|\| 60 \* 60 \* 1000/);
  assert.match(recovery, /const RECOVERY_TRIGGER_MS = TIMEOUT_POLICY\.recoveryTriggerMs \|\| GENERATION_TIMEOUT_MS/);
  assert.match(recovery, /location\.reload\(\)/);
  assert.match(recovery, /function usageLimited\(\)/);
  assert.match(recovery, /function replacementReason\(\)/);
  assert.match(recovery, /phase: 'preserve_current_chat'/);
  assert.match(recovery, /no_verified_usage_or_context_exhaustion/);
  assert.match(recovery, /CHAT_RECOVERED_RETRY/);
  assert.match(recovery, /operation_type: 'new_chat'/);
  assert.match(recovery, /response_text: bounded/);
  assert.match(recovery, /await report\('chatgpt_response'/);
  assert.match(recovery, /current\.status === 'failed'/);
});

test('operation lookup route is accepted by the MV3 service worker allowlist', () => {
  assert.ok(background.includes("const BRIDGE_OPERATION_RE = /^\\/operation\\?operation_id=[^&]{1,200}$/;"));
});

test('native controller can poll the queue through the MV3 worker', () => {
  assert.match(background, /'GET \/next-operation'/);
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
  assert.match(content, /void reportObservation\('chatgpt_response'/);
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
  assert.match(content, /async function finishOperation\(operationId, responseText = '', requireResponseText = false, timing = null\)/);
  assert.match(content, /if \(requireResponseText && \(typeof responseText !== 'string' \|\| !responseText\.trim\(\)\)\)/);
  assert.match(content, /await finishOperation\(operation\.operation_id, response, true, browserTiming\)/);
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

test('background watchdog requires an active operation and exact chat identity before reloading', () => {
  assert.match(background, /if \(typeof health\.data\.active_operation_id !== 'string' \|\| !health\.data\.active_operation_id\.trim\(\)\) return/);
  assert.match(background, /if \(typeof health\.data\.chat_url !== 'string' \|\| !health\.data\.chat_url\.trim\(\)\) return/);
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
  assert.match(content, /const baseline = typeof stored\?\.baseline === 'string' \? stored\.baseline : fingerprint\(\)/);
  assert.match(content, /const visibleResponse = latestAssistant\(\)/);
  assert.match(content, /visibleFingerprint !== baseline/);
  assert.match(content, /finishOperation\(stored\.operation_id, visibleResponse, true\)/);
});
