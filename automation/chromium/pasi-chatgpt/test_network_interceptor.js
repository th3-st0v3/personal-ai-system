const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  createPasiNetworkInterceptor,
  isConversationGenerationRequest,
  parseStatus,
  classifyPayload,
  parseStreamLines
} = require('./network-interceptor.js');

function responseFromChunks(chunks, { status = 200, ok = true } = {}) {
  const makeReader = () => ({
    index: 0,
    async read() {
      if (this.index >= chunks.length) return { done: true, value: undefined };
      const value = new TextEncoder().encode(chunks[this.index++]);
      return { done: false, value };
    }
  });
  return {
    ok,
    status,
    body: { getReader: makeReader },
    clone() {
      return responseFromChunks(chunks, { status, ok });
    }
  };
}

function fakeTimers() {
  const callbacks = new Set();
  return {
    setInterval(fn) { callbacks.add(fn); return fn; },
    clearInterval(id) { callbacks.delete(id); },
    tick() { for (const fn of [...callbacks]) fn(); },
    size() { return callbacks.size; }
  };
}

test('recognizes only POST conversation generation requests', () => {
  assert.equal(isConversationGenerationRequest('https://chatgpt.com/backend-api/conversation', { method: 'POST' }), true);
  assert.equal(isConversationGenerationRequest('https://chatgpt.com/backend-api/conversation', { method: 'GET' }), false);
  assert.equal(isConversationGenerationRequest('https://chatgpt.com/assets.js', { method: 'POST' }), false);
});

test('classifies HTTP and provider failures without DOM dependencies', () => {
  assert.deepEqual(parseStatus(401), { eventType: 'FAILED', reason: 'AUTHENTICATION_EXPIRED', classification: 'auth_failure' });
  assert.deepEqual(parseStatus(429), { eventType: 'FAILED', reason: 'RATE_LIMIT_HTTP', classification: 'usage_limit' });
  assert.equal(classifyPayload({ error: { code: 'context_length_exceeded' } }).reason, 'CONTEXT_EXHAUSTED');
  assert.equal(classifyPayload({ error: { code: 'rate_limit_exceeded' } }).reason, 'USAGE_LIMIT_REACHED');
});

test('parses SSE data lines incrementally and preserves an incomplete tail', () => {
  const seen = [];
  const tail = parseStreamLines('data: {"ok":1}\n\ndata: {"ok":2}', value => seen.push(value));
  assert.deepEqual(seen, ['{"ok":1}']);
  assert.equal(tail, 'data: {"ok":2}');
});

test('intercepts generation traffic non-invasively and reports STARTED then COMPLETED', async () => {
  const events = [];
  const target = { fetch: async () => responseFromChunks(['data: {"delta":"hi"}\n\n', 'data: [DONE]\n\n']) };
  const interceptor = createPasiNetworkInterceptor({
    target,
    emit: event => events.push(event),
    randomId: (() => {
      let n = 0;
      return () => `id-${++n}`;
    })()
  });
  interceptor.bindOperation('op-1');
  assert.equal(interceptor.install(), true);
  const response = await target.fetch('https://chatgpt.com/backend-api/conversation', { method: 'POST' });
  assert.equal(response.ok, true);
  assert.equal(response.status, 200);
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(events.map(event => event.eventType), ['STARTED', 'COMPLETED']);
  assert.equal(events[0].operationId, 'op-1');
  assert.equal(events[0].requestId, events[1].requestId);
  assert.match(events[0].requestId, /^REQ-.*-1$/);
});

test('does not intercept unrelated requests', async () => {
  let called = 0;
  const original = async () => {
    called += 1;
    return { ok: true, status: 200 };
  };
  const target = { fetch: original };
  const events = [];
  const interceptor = createPasiNetworkInterceptor({ target, emit: event => events.push(event) });
  interceptor.install();
  await target.fetch('https://chatgpt.com/backend-api/files', { method: 'POST' });
  assert.equal(called, 1);
  assert.deepEqual(events, []);
});

test('suppresses duplicate terminal transitions', async () => {
  const events = [];
  const target = {
    fetch: async () =>
      responseFromChunks([
        'data: {"error":{"code":"context_length_exceeded"}}\n\n',
        'data: [DONE]\n\n'
      ])
  };
  const interceptor = createPasiNetworkInterceptor({
    target,
    emit: event => events.push(event),
    randomId: () => 'fixed'
  });
  interceptor.install();
  await target.fetch('https://chatgpt.com/backend-api/conversation', { method: 'POST' });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(events.map(event => event.eventType), ['STARTED', 'INTERRUPTED']);
});

test('classifies stream reader failures as retryable transport failures', async () => {
  const events = [];
  const target = {
    fetch: async () => ({
      ok: true,
      status: 200,
      clone() {
        return {
          body: {
            getReader: () => ({
              read: async () => {
                throw new Error('socket closed');
              }
            })
          }
        };
      }
    })
  };
  const interceptor = createPasiNetworkInterceptor({ target, emit: event => events.push(event) });
  interceptor.install();
  await target.fetch('https://chatgpt.com/backend-api/conversation', { method: 'POST' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(events.at(-1).eventType, 'INTERRUPTED');
  assert.equal(events.at(-1).classification, 'retryable_transport_failure');
});

test('stall detection emits exactly one terminal interruption and clears its timer', async () => {
  const events = [];
  const timers = fakeTimers();
  let clock = 0;
  let resolveRead;
  const target = {
    fetch: async () => ({
      ok: true,
      status: 200,
      clone() {
        return {
          body: {
            getReader: () => ({
              read: () =>
                new Promise(resolve => {
                  resolveRead = resolve;
                })
            })
          }
        };
      }
    })
  };
  const interceptor = createPasiNetworkInterceptor({
    target,
    emit: event => events.push(event),
    now: () => clock,
    stallThresholdMs: 1000,
    setIntervalImpl: timers.setInterval,
    clearIntervalImpl: timers.clearInterval
  });
  interceptor.install();
  await target.fetch('https://chatgpt.com/backend-api/conversation', { method: 'POST' });
  clock = 1000;
  timers.tick();
  resolveRead({ done: true, value: undefined });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(events.map(event => event.eventType), ['STARTED', 'INTERRUPTED']);
  assert.equal(timers.size(), 0);
});

test('installation is idempotent and health exposes current operation/request', () => {
  const target = { fetch: async () => ({ ok: true, status: 200 }) };
  const interceptor = createPasiNetworkInterceptor({
    target,
    now: () => 1234,
    randomId: () => 'req-1'
  });
  assert.equal(interceptor.install(), true);
  assert.equal(interceptor.install(), false);
  interceptor.bindOperation('op-9');
  assert.deepEqual(interceptor.health(), {
    status: 'HEALTHY',
    timestamp: 1234,
    installed: true,
    trackingRequestId: null,
    currentOperationId: 'op-9'
  });
});
