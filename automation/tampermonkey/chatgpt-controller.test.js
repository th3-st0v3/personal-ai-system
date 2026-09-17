const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const controllerPath = path.join(__dirname, 'chatgpt-controller.user.js');
const source = fs.readFileSync(controllerPath, 'utf8');

test('controller declares the expected current version', () => {
    assert.match(source, /@version\s+2\.3\.0/);
});

test('controller handles the semantic GitHub attachment operation', () => {
    assert.match(source, /operation\.operation_type === ['"]attach_github['"]/);
    assert.match(source, /attachGitHubContext\(operation\.prompt\)/);
});

test('controller discovers the ChatGPT plus and GitHub controls semantically', () => {
    assert.match(source, /Add files and more/);
    assert.match(source, /function findPlusControl\(/);
    assert.match(source, /function findGitHubControl\(/);
    assert.match(source, /function findRepositoryPicker\(/);
});

test('controller fails closed when GitHub cannot be activated', () => {
    assert.match(source, /GitHub app was not found in the ChatGPT menu/);
    assert.match(source, /GitHub app reported that repository access is unavailable/);
});

test('controller retains guarded prompt submission and generation checks', () => {
    assert.match(source, /function submitPromptWithRecovery\(/);
    assert.match(source, /Submit attempt ' \+ attempt/);
    assert.match(source, /ChatGPT prompt submission did not leave the composer/);
    assert.match(source, /function waitUntilGenerationOrSubmissionSettles\(/);
});
