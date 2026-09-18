const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const controllerPath = path.join(__dirname, 'chatgpt-controller.user.js');
const source = fs.readFileSync(controllerPath, 'utf8');

test('controller declares the current hardened version', () => {
    assert.match(source, /@version\s+2\.4\.8/);
    assert.match(source, /CONTROLLER_VERSION = ['"]2\.4\.8['"]/);
});

test('controller supports conditional reasoning selection', () => {
    assert.match(source, /operation\.operation_type === ['"]select_reasoning['"]/);
    assert.match(source, /function selectReasoningMode\(/);
    assert.match(source, /Thinking control was not found/);
});

test('controller supports conditional GitHub attachment', () => {
    assert.match(source, /operation\.operation_type === ['"]attach_github['"]/);
    assert.match(source, /function attachGitHubContext\(/);
    assert.match(source, /githubContextAlreadyAttached/);
    assert.match(source, /function findGitHubControl\(/);
    assert.match(source, /function findRepositoryPicker\(/);
});

test('controller extracts live assistant responses and reports them', () => {
    assert.match(source, /function extractLatestAssistantResponse\(/);
    assert.match(source, /data-message-author-role=\\?"assistant/);
    assert.match(source, /kind: ['"]chatgpt_response['"]/);
    assert.match(source, /response_text_available: true/);
});

test('controller sends the verified response directly with completion acknowledgement', () => {
    assert.match(source, /void reportResponseObservation\(response\)/);
    assert.match(source, /await reportFinished\(operation\.operation_id, response\)/);
    assert.match(source, /function reportFinished\(operationId, responseText\)/);
    assert.match(source, /status === 'completed' && payload\.operation\.response_text_available === true/);
    assert.match(source, /if \(typeof responseText === 'string'\) body\.response_text = responseText\.slice\(0, 50000\)/);
    assert.match(source, /for \(var attempt = 1; attempt <= 3; attempt \+= 1\)/);
    assert.match(source, /\/operation\?operation_id=/);
    assert.match(source, /response_text_available: typeof responseText === 'string' && Boolean\(responseText\.trim\(\)\)/);
});

test('controller treats response observation as best-effort instead of blocking completion', () => {
    assert.match(source, /async function reportResponseObservation\(responseText\) \{/);
    assert.match(source, /try \{/);
    assert.match(source, /Could not persist ChatGPT response observation; completion path remains authoritative/);
    assert.match(source, /catch \(error\)/);
});

test('controller distinguishes context exhaustion from provider usage exhaustion', () => {
    assert.match(source, /function isConversationContextExhaustedVisible\(/);
    assert.match(source, /function isUsageLimitedVisible\(/);
    assert.match(source, /CHAT_EXHAUSTED:/);
    assert.match(source, /CHAT_USAGE_LIMITED:/);
    assert.match(source, /context limit reached/);
    assert.match(source, /start a new chat to continue/);
});

test('controller recognizes chat identity changes instead of silently reusing stale state', () => {
    assert.match(source, /lastKnownChatUrl/);
    assert.match(source, /kind: 'chatgpt_chat_changed'/);
    assert.match(source, /previous_chat_url/);
    assert.match(source, /new_chat_url/);
    assert.match(source, /conversationSignature/);
});

test('controller continuously reports state even while an operation is active', () => {
    assert.match(source, /setInterval\(function \(\) \{ reportChatState\(true\); \}, STATE_INTERVAL_MS\)/);
    assert.match(source, /active_operation_id/);
    assert.match(source, /reason: processing \? 'during_operation' : 'navigation'/);
});

test('controller retains guarded prompt submission with bounded explicit acknowledgement', () => {
    assert.match(source, /SUBMISSION_ACK_MS = 2500/);
    assert.match(source, /SUBMISSION_ATTEMPTS = 3/);
    assert.match(source, /function newestUserMatches\(/);
    assert.match(source, /function waitForSubmissionAck\(/);
    assert.match(source, /prompt submission could not be verified after bounded attempts/);
    assert.match(source, /function waitForAssistantResponse\(/);
    assert.match(source, /function isGenerating\(/);
});

test('controller requires verified new-chat identity before considering new_chat complete', () => {
    assert.match(source, /var previousChat = chatUrl\(\)/);
    assert.match(source, /var differentChat = Boolean\(previousChat && currentChat && currentChat !== previousChat\)/);
    assert.match(source, /var initialChatReady = !previousChat/);
    assert.match(source, /previousChat && \(!currentChat \|\| currentChat === previousChat\)/);
});

test('controller preserves interrupted operations until the bridge acknowledges recovery', () => {
    assert.match(source, /browser page reloaded during operation/);
    assert.match(source, /if \(ok\) localStorage\.removeItem\(ACTIVE_KEY\)/);
    assert.match(source, /var finalized = false/);
    assert.match(source, /if \(finalized\) localStorage\.removeItem\(ACTIVE_KEY\)/);
});