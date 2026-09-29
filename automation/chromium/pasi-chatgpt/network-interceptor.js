(() => {
  'use strict';

  const DEFAULT_ENDPOINT_MARKER = '/backend-api/conversation';
  const DEFAULT_STALL_THRESHOLD_MS = 8000;
  const TERMINAL_EVENTS = new Set(['COMPLETED', 'INTERRUPTED', 'FAILED']);
  const ERROR_CLASSIFICATIONS = Object.freeze({
    context: 'context_exhaustion',
    usage: 'usage_limit',
    auth: 'auth_failure',
    provider: 'provider_failure',
    transport: 'retryable_transport_failure'
  });

  function requestDetails(input, init) {
    if (typeof input === 'string' || input instanceof URL) {
      return { url: String(input), method: String(init?.method || 'GET').toUpperCase() };
    }
    if (input && typeof input === 'object') {
      return {
        url: String(input.url || ''),
        method: String(init?.method || input.method || 'GET').toUpperCase()
      };
    }
    return { url: '', method: String(init?.method || 'GET').toUpperCase() };
  }

  function isConversationGenerationRequest(input, init, marker = DEFAULT_ENDPOINT_MARKER) {
    const request = requestDetails(input, init);
    return request.method === 'POST' && request.url.includes(marker);
  }

  function parseStatus(status) {
    const value = Number(status);
    if (value === 401 || value === 403) {
      return { eventType: 'FAILED', reason: 'AUTHENTICATION_EXPIRED', classification: ERROR_CLASSIFICATIONS.auth };
    }
    if (value === 429) {
      return { eventType: 'FAILED', reason: 'RATE_LIMIT_HTTP', classification: ERROR_CLASSIFICATIONS.usage };
    }
    if (value >= 400) {
      return { eventType: 'FAILED', reason: 'HTTP_ERROR_STATUS', classification: ERROR_CLASSIFICATIONS.provider };
    }
    return null;
  }

  function classifyPayload(payload) {
    const error = payload?.error && typeof payload.error === 'object' ? payload.error : null;
    const code = String(error?.code || '').toLowerCase();
    const message = String(error?.message || payload?.message || '').toLowerCase();
    const status = String(payload?.status || '').toLowerCase();

    if (
      code === 'context_length_exceeded'
      || message.includes('context length')
      || message.includes('max token')
      || message.includes('maximum context')
    ) {
      return {
        eventType: 'INTERRUPTED',
        reason: 'CONTEXT_EXHAUSTED',
        classification: ERROR_CLASSIFICATIONS.context,
        telemetry: { providerErrorCode: error?.code || null }
      };
    }

    if (
      code === 'rate_limit_exceeded'
      || status === 'exhausted'
      || message.includes('rate limit')
      || message.includes('usage limit')
    ) {
      return {
        eventType: 'INTERRUPTED',
        reason: 'USAGE_LIMIT_REACHED',
        classification: ERROR_CLASSIFICATIONS.usage,
        telemetry: { providerErrorCode: error?.code || null }
      };
    }

    return null;
  }

  function parseStreamLines(text, onData) {
    let buffer = String(text || '');
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const rawLine = buffer.slice(0, newline).replace(/\r$/, '');
      buffer = buffer.slice(newline + 1);
      const line = rawLine.trim();
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;
      onData(raw);
    }
    return buffer;
  }

  function createPasiNetworkInterceptor(options = {}) {
    const target = options.target || globalThis;
    const endpointMarker = String(options.endpointMarker || DEFAULT_ENDPOINT_MARKER);
    const stallThresholdMs = Number.isFinite(options.stallThresholdMs) && options.stallThresholdMs > 0
      ? options.stallThresholdMs
      : DEFAULT_STALL_THRESHOLD_MS;
    const now = typeof options.now === 'function' ? options.now : Date.now;
    const setIntervalImpl = options.setIntervalImpl || setInterval;
    const clearIntervalImpl = options.clearIntervalImpl || clearInterval;
    const randomId = typeof options.randomId === 'function'
      ? options.randomId
      : () => `EVT-${now()}-${Math.random().toString(16).slice(2)}`;
    const emitExternal = typeof options.emit === 'function' ? options.emit : () => {};
    const decoderFactory = typeof options.decoderFactory === 'function'
      ? options.decoderFactory
      : () => new TextDecoder('utf-8');

    const state = {
      currentOperationId: null,
      activeGeneration: null,
      requestCounter: 0,
      installed: false,
      originalFetch: null,
      boundHandler: null
    };

    function emit(eventType, trackingState, payload = {}) {
      if (trackingState && trackingState.isTerminal && TERMINAL_EVENTS.has(eventType)) return false;
      if (trackingState && TERMINAL_EVENTS.has(eventType)) trackingState.isTerminal = true;

      const event = {
        eventType,
        eventId: randomId(),
        operationId: state.currentOperationId,
        requestId: trackingState?.requestId || null,
        timestamp: now(),
        ...payload,
        telemetry: payload.telemetry || {}
      };
      emitExternal(event);
      return true;
    }

    function markPayloadFailure(raw, trackingState) {
      if (raw === '[DONE]') return false;
      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (_) {
        return false;
      }
      const classification = classifyPayload(parsed);
      if (!classification) return false;
      emit(classification.eventType, trackingState, classification);
      return true;
    }

    async function observeResponse(response, trackingState) {
      if (!response || !response.body || typeof response.body.getReader !== 'function') {
        emit('COMPLETED', trackingState, {
          telemetry: { totalChunksProcessed: 0, bodyObserved: false }
        });
        return;
      }

      let intervalId = null;
      let lastChunkAt = now();
      let chunkCount = 0;
      let bufferedText = '';
      try {
        const reader = response.body.getReader();
        const decoder = decoderFactory();

        const checkStall = () => {
          if (trackingState.isTerminal) {
            if (intervalId !== null) clearIntervalImpl(intervalId);
            return;
          }
          const elapsed = now() - lastChunkAt;
          if (elapsed >= stallThresholdMs) {
            emit('INTERRUPTED', trackingState, {
              reason: 'GENERATION_STALLED',
              classification: ERROR_CLASSIFICATIONS.transport,
              telemetry: { durationSinceLastChunk: elapsed }
            });
            if (intervalId !== null) clearIntervalImpl(intervalId);
          }
        };

        intervalId = setIntervalImpl(
          checkStall,
          Math.max(250, Math.min(2000, Math.floor(stallThresholdMs / 4)))
        );

        while (true) {
          const result = await reader.read();

          if (result.done) {
            bufferedText += decoder.decode();
            parseStreamLines(bufferedText + '\n', raw => {
              if (!trackingState.isTerminal) markPayloadFailure(raw, trackingState);
            });
            if (!trackingState.isTerminal) {
              emit('COMPLETED', trackingState, {
                telemetry: { totalChunksProcessed: chunkCount }
              });
            }
            break;
          }

          lastChunkAt = now();
          chunkCount += 1;
          bufferedText += decoder.decode(result.value, { stream: true });
          bufferedText = parseStreamLines(bufferedText, raw => {
            if (!trackingState.isTerminal) markPayloadFailure(raw, trackingState);
          });
        }
      } catch (error) {
        if (!trackingState.isTerminal) {
          emit('INTERRUPTED', trackingState, {
            reason: 'NETWORK_STREAM_DISCONNECTED',
            classification: ERROR_CLASSIFICATIONS.transport,
            telemetry: {
              errorMessage: String(error?.message || error).slice(0, 300),
              totalChunksProcessed: chunkCount
            }
          });
        }
      } finally {
        if (intervalId !== null) clearIntervalImpl(intervalId);
      }
    }

    async function interceptedFetch(...args) {
      if (!isConversationGenerationRequest(args[0], args[1], endpointMarker)) {
        return state.originalFetch.apply(this, args);
      }

      state.requestCounter += 1;
      const trackingState = {
        requestId: `REQ-${now()}-${state.requestCounter}`,
        isTerminal: false,
        chunkCount: 0,
        startTime: now()
      };
      state.activeGeneration = trackingState;

      emit('STARTED', trackingState, {
        telemetry: { requestUri: requestDetails(args[0], args[1]).url }
      });

      try {
        const response = await state.originalFetch.apply(this, args);
        const statusFailure = !response.ok ? parseStatus(response.status) : null;
        if (statusFailure) {
          emit('FAILED', trackingState, {
            ...statusFailure,
            telemetry: { httpStatus: response.status }
          });
          return response;
        }

        let cloned;
        try {
          cloned = response.clone();
        } catch (error) {
          emit('FAILED', trackingState, {
            reason: 'RESPONSE_CLONE_FAILED',
            classification: ERROR_CLASSIFICATIONS.transport,
            telemetry: {
              errorMessage: String(error?.message || error).slice(0, 300)
            }
          });
          return response;
        }

        void observeResponse(cloned, trackingState);
        return response;
      } catch (error) {
        emit('FAILED', trackingState, {
          reason: 'TRANSPORT_ESTABLISHMENT_FAILED',
          classification: ERROR_CLASSIFICATIONS.transport,
          telemetry: {
            errorMessage: String(error?.message || error).slice(0, 300)
          }
        });
        throw error;
      }
    }

    function bindOperation(operationId) {
      state.currentOperationId = operationId == null || operationId === ''
        ? null
        : String(operationId);
      return state.currentOperationId;
    }

    function health() {
      return {
        status: 'HEALTHY',
        timestamp: now(),
        installed: state.installed,
        trackingRequestId: state.activeGeneration?.requestId || null,
        currentOperationId: state.currentOperationId
      };
    }

    function install() {
      if (state.installed) return false;
      if (!target || typeof target.fetch !== 'function') {
        throw new Error('PASI interceptor requires a fetch target');
      }
      state.originalFetch = target.fetch;
      target.fetch = interceptedFetch;
      state.installed = true;
      return true;
    }

    function uninstall() {
      if (!state.installed) return false;
      target.fetch = state.originalFetch;
      state.installed = false;
      state.originalFetch = null;
      return true;
    }

    function bindOperationEventListener() {
      if (typeof target.addEventListener !== 'function') return false;
      if (state.boundHandler) return true;
      state.boundHandler = event => {
        const detail = event?.detail;
        const operationId = typeof detail === 'string' ? detail : detail?.operationId;
        bindOperation(operationId);
      };
      target.addEventListener('PASI_NETWORK_BIND_OPERATION', state.boundHandler);
      return true;
    }

    return Object.freeze({
      install,
      uninstall,
      bindOperation,
      bindOperationEventListener,
      health,
      isGenerationRequest: (input, init) =>
        isConversationGenerationRequest(input, init, endpointMarker),
      state
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      DEFAULT_STALL_THRESHOLD_MS,
      createPasiNetworkInterceptor,
      isConversationGenerationRequest,
      parseStatus,
      classifyPayload,
      parseStreamLines
    };
  }

  if (typeof globalThis !== 'undefined') {
    globalThis.PASI_NETWORK_INTERCEPTOR_API = Object.freeze({
      DEFAULT_STALL_THRESHOLD_MS,
      createPasiNetworkInterceptor,
      isConversationGenerationRequest,
      parseStatus,
      classifyPayload,
      parseStreamLines
    });

    if (globalThis.window === globalThis && typeof globalThis.fetch === 'function') {
      if (!globalThis.__PASI_NETWORK_INTERCEPTOR__) {
        const interceptor = createPasiNetworkInterceptor({
          target: globalThis,
          emit: event => {
            globalThis.dispatchEvent(new CustomEvent('PASI_NETWORK_LIFECYCLE', {
              detail: JSON.stringify(event)
            }));
          }
        });
        interceptor.bindOperationEventListener();
        interceptor.install();
        globalThis.__PASI_NETWORK_INTERCEPTOR__ = interceptor;
        globalThis.__PASI_NETWORK_INTERCEPTOR_HEALTH__ = () => interceptor.health();
      }
    }
  }
})();
