const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const controllerPath = path.join(__dirname, 'chatgpt-controller.user.js');
const source = fs.readFileSync(controllerPath, 'utf8');

test('controller declares the expected current version', () => {
    assert.match(source, /@version\s+2\.4\.3/);
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

test('controller treats only conversation/context exhaustion as new-chat exhaustion', () => {
    assert.match(source, /function isConversationContextExhaustedVisible\(/);
    assert.match(source, /CHAT_EXHAUSTED:/);
    assert.match(source, /context limit reached/);
    assert.match(source, /start a new chat to continue/);
    assert.doesNotMatch(source, /'current usage limit'/);
    assert.doesNotMatch(source, /'usage limit reached'/);
    assert.doesNotMatch(source, /'free tier limit'/);
});

test('controller avoids state overwrite while an operation is active', () => {
    assert.match(source, /if \(!force && \(processing \|\| activeOperationId !== null\)\) return;/);
    assert.match(source, /await reportChatState\(true\)/);
});

test('controller retains guarded prompt submission and generation checks', () => {
    assert.match(source, /Submit attempt ' \+ attempt/);
    assert.match(source, /ChatGPT prompt submission did not leave the composer/);
    assert.match(source, /function waitForAssistantResponse\(/);
    assert.match(source, /function isGenerating\(/);
});

test('controller continuously reports state without creating chats', () => {
    assert.match(source, /setInterval\(reportChatState/);
    assert.match(source, /kind: ['"]chatgpt_state['"]/);
    assert.match(source, /conversation_context_exhausted/);
    assert.match(source, /chat_exhausted/);
    assert.match(source, /github_attached/);
});
