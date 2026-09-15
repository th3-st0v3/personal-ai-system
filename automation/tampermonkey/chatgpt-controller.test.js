const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const controllerPath = path.join(
    __dirname,
    'chatgpt-controller.user.js'
);

function extractFunction(source, functionName) {
    const marker = `function ${functionName}(`;
    const start = source.indexOf(marker);

    assert.notEqual(
        start,
        -1,
        `Could not find ${functionName} in controller.`
    );

    const bodyStart = source.indexOf('{', start);
    assert.notEqual(bodyStart, -1);

    let depth = 0;
    let inString = null;
    let escaped = false;
    let inLineComment = false;
    let inBlockComment = false;

    for (let index = bodyStart; index < source.length; index += 1) {
        const char = source[index];
        const next = source[index + 1];

        if (inLineComment) {
            if (char === '\n') {
                inLineComment = false;
            }
            continue;
        }

        if (inBlockComment) {
            if (char === '*' && next === '/') {
                inBlockComment = false;
                index += 1;
            }
            continue;
        }

        if (inString) {
            if (escaped) {
                escaped = false;
            } else if (char === '\\') {
                escaped = true;
            } else if (char === inString) {
                inString = null;
            }
            continue;
        }

        if (
            (char === '/' && next === '/') ||
            (char === '/' && next === '*')
        ) {
            if (next === '/') {
                inLineComment = true;
            } else {
                inBlockComment = true;
            }
            index += 1;
            continue;
        }

        if (
            char === '"' ||
            char === "'" ||
            char === '`'
        ) {
            inString = char;
            continue;
        }

        if (char === '{') {
            depth += 1;
        } else if (char === '}') {
            depth -= 1;

            if (depth === 0) {
                return source.slice(start, index + 1);
            }
        }
    }

    throw new Error(
        `Could not extract ${functionName}.`
    );
}

function loadResolver() {
    const source = fs.readFileSync(
        controllerPath,
        'utf8'
    );

    const resolver = extractFunction(
        source,
        'findNewChatFromObservation'
    );

    const visibility = extractFunction(
        source,
        'isVisible'
    );

    const context = {
        document: null,
        window: {
            getComputedStyle(element) {
                return element.style || {
                    display: 'block',
                    visibility: 'visible',
                    opacity: '1'
                };
            }
        }
    };

    vm.createContext(context);
    vm.runInContext(
        `${visibility}\n${resolver}\nthis.resolve = findNewChatFromObservation;`,
        context
    );

    return (observation, elements) => {
        context.document = {
            querySelectorAll(selector) {
                assert.equal(
                    selector,
                    '[data-pasi-id]'
                );
                return elements;
            }
        };

        return context.resolve(observation);
    };
}

function loadStateVerifier() {
    const source = fs.readFileSync(
        controllerPath,
        'utf8'
    );

    const verifier = extractFunction(
        source,
        'isNewChatStateReady'
    );

    const context = {
        findComposer(observation) {
            return observation?.testComposer || null;
        }
    };

    vm.createContext(context);
    vm.runInContext(
        `${verifier}\nthis.verify = isNewChatStateReady;`,
        context
    );

    return context.verify;
}

function makeElement(id, visible = true) {
    return {
        style: {
            display: visible ? 'block' : 'none',
            visibility: 'visible',
            opacity: '1'
        },
        getAttribute(name) {
            if (name === 'data-pasi-id') {
                return id;
            }
            return null;
        },
        getClientRects() {
            return visible ? [{}] : [];
        }
    };
}

test('new_chat observation resolves the matching visible DOM element', () => {
    const resolve = loadResolver();
    const target = makeElement('pasi-a-new-chat');
    const other = makeElement('pasi-b-other');

    const result = resolve(
        {
            interactive_elements: [
                {
                    id: 'pasi-a-new-chat',
                    control: 'new_chat',
                    role: 'link',
                    name: 'New chat'
                }
            ]
        },
        [other, target]
    );

    assert.equal(result, target);
});

test('new_chat observation ignores non-new-chat and hidden elements', () => {
    const resolve = loadResolver();
    const hiddenTarget = makeElement(
        'pasi-hidden-new-chat',
        false
    );
    const visibleOther = makeElement('pasi-visible-other');

    const result = resolve(
        {
            interactive_elements: [
                {
                    id: 'pasi-hidden-new-chat',
                    control: 'new_chat',
                    role: 'link',
                    name: 'New chat'
                },
                {
                    id: 'pasi-visible-other',
                    control: 'composer',
                    role: 'textbox'
                }
            ]
        },
        [hiddenTarget, visibleOther]
    );

    assert.equal(result, null);
});

test('new_chat state verifies a fresh observation, changed URL, and composer', () => {
    const verify = loadStateVerifier();
    const clickTimestamp = Date.parse('2026-09-15T10:00:00.000Z');

    const result = verify(
        'https://chatgpt.com/c/old-chat',
        clickTimestamp,
        {
            captured_at: '2026-09-15T10:00:01.000Z',
            page: {
                url: 'https://chatgpt.com/c/new-chat'
            },
            interactive_elements: [],
            testComposer: { id: 'pasi-composer' }
        },
        'https://chatgpt.com/c/new-chat'
    );

    assert.equal(result, true);
});

test('new_chat state rejects stale or unchanged navigation', () => {
    const verify = loadStateVerifier();
    const clickTimestamp = Date.parse('2026-09-15T10:00:00.000Z');
    const observation = {
        captured_at: '2026-09-15T09:59:59.000Z',
        page: {
            url: 'https://chatgpt.com/c/old-chat'
        },
        interactive_elements: [],
        testComposer: { id: 'pasi-composer' }
    };

    assert.equal(
        verify(
            'https://chatgpt.com/c/old-chat',
            clickTimestamp,
            observation,
            'https://chatgpt.com/c/old-chat'
        ),
        false
    );
});
