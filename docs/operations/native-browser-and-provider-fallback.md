# Native Browser And Provider Fallback

PASI now has a native Chromium Manifest V3 controller at `automation/chromium/pasi-chatgpt/`.

## Browser control

The native extension replaces Tampermonkey for the core ChatGPT path. It uses standard browser `fetch()` to talk to the localhost PASI bridge, reports ChatGPT health, executes the existing bridge operations, and records an interrupted operation in `localStorage` so a page reload returns that work to the retry path.

The extension service worker checks the bridge queue and browser heartbeat. When work is queued but the ChatGPT observation becomes stale, it can reload an available ChatGPT tab. Refreshes are bounded and are skipped when an authentication or security challenge is visible.

Tampermonkey remains a fallback while the native extension is being adopted. Do not run duplicate controllers at the same time.

## Provider fallback

`scripts/pasi_provider_router.py` is dependency-light and uses only the Python standard library plus the existing repository context helper. It tries configured providers in this order:

1. OpenRouter through `OPENROUTER_API_KEY`.
2. Perplexity through `PERPLEXITY_API_KEY`.
3. Local OpenCode through the `opencode` executable when installed.

Fallback providers are evidence/model sources only. The unattended runner still applies repository patches only after the normal PASI completion contract, patch-path checks, and canonical validation pass.

## Web research

`python scripts/pasi_research.py --search "query"` uses the configured Perplexity search API.

`python scripts/pasi_research.py --read "https://example.com"` uses the existing bounded HTTPS research adapter. HTTPS, public-address, content-type, response-size, and content-length protections remain active.

## Ollama context policy

Ollama is an optional local fallback, not the primary PASI execution surface. The Windows/macOS Ollama app can provide a server-level context-length default; set that baseline to **32K tokens** for PASI's current local `qwen3:8b` fallback.

PASI also sends an explicit `options.num_ctx` value on every Ollama chat request so unattended behavior does not depend on a GUI default. The default is `32768` and can be deliberately overridden with:

```text
PASI_OLLAMA_CONTEXT_TOKENS=<tokens>
```

The currently installed `qwen3:8b` Ollama tag provides a **40K-token** context window, so configuring the app to 256K does not turn this model into a 256K model. The 32K PASI default leaves headroom below the model ceiling for output and runtime memory.

Do not silently raise PASI to the maximum context merely because the Ollama UI offers a larger global value. Larger contexts consume more memory; use a larger-context model/tag and a measured hardware budget before increasing this default.

## Failure behavior

PASI distinguishes provider usage limits, authentication challenges, browser-runtime loss, and conversation-context exhaustion. A provider-wide usage limit does not cause a new-chat rollover. A stale browser controller can place the runner in bounded standby until the browser recovers, while fallback providers can continue work when configured.

No fallback provider receives repository credentials automatically. Public repository content is the normal repository context source.
