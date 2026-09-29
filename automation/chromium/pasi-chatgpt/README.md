# PASI Native ChatGPT Controller

This is the native Chromium replacement for the PASI Tampermonkey controller.

## Install

Build the clean native extension before loading it. From the repository root, run:

`./.venv/bin/python scripts/build_chromium_extension.py --archive`

Open `chrome://extensions` in Chromium or Chrome, enable **Developer mode**, choose **Load unpacked**, and select the generated staging directory:

`.runtime/chromium/pasi-chatgpt`

The build is allowlisted and rejects reserved underscore-prefixed entries and Python bytecode, so `__pycache__`/`.pyc` files cannot enter the unpacked extension. The optional archive is also validated before it is produced.

Open `https://chatgpt.com/` and verify the PASI bridge is running on `127.0.0.1:8765`.

## Operation

The content script consumes the same PASI bridge operations used by the existing controller:

- `new_chat`
- `select_reasoning`
- `attach_github`
- `prompt`

It reports `chatgpt_health`, `chatgpt_state`, and completed response observations through the existing bridge.

The service worker watches queued work. When the browser heartbeat becomes stale, it can reload a ChatGPT tab with a bounded refresh budget. Authentication or security challenges stop automatic refresh attempts.

A page reload during an active operation is recorded in browser-local storage. The next startup reports that operation as failed so the overnight supervisor can retry instead of leaving a stale claimed operation trapped in the queue.

## Migration from Tampermonkey

Use the native extension as the only active ChatGPT controller. Keep the existing Tampermonkey controller disabled but installed until the native path has been validated on the local machine.

Do not run both controllers simultaneously; both can consume the same bridge queue and would create duplicate operations.

## PASI Control Center

The native controller exposes a Chromium Side Panel using the sidePanel permission and sidepanel.html. Click the extension action icon to open it.

The first panel milestone is intentionally read-only with respect to privileged automation. It provides:

- raw roadmap import and local persistence;
- structured task preview with dependency-aware drag/drop and keyboard reordering;
- bridge/controller health telemetry using the existing authenticated background boundary;
- a Satellite/local-workstation/beast preference that does not claim to apply host limits from inside the browser.

Cloud roadmap dissection, runner start/stop/force-skip commands, and network-stream interception remain separate milestones with explicit contracts.

## Phase 1 — Network interceptor test path

Phase 1 adds a **read-only transport observer** for ChatGPT generation requests. It runs in the page's `MAIN` JavaScript world so it can wrap the page's native `fetch()`; the existing DOM controller remains responsible for production operation handling during this phase.

The interceptor is deliberately isolated from the PASI bridge. It emits bounded lifecycle events through `PASI_NETWORK_LIFECYCLE` and exposes `window.__PASI_NETWORK_INTERCEPTOR_HEALTH__()`.

Run the deterministic Phase 1 tests locally:

`node --test automation/chromium/pasi-chatgpt/test_network_interceptor.js`

For a live browser smoke check, load the built extension, open ChatGPT, then use the page console:

```js
const events = [];
window.addEventListener('PASI_NETWORK_LIFECYCLE', event => {
  events.push(JSON.parse(event.detail));
  console.log(events.at(-1));
});
window.dispatchEvent(new CustomEvent('PASI_NETWORK_BIND_OPERATION', {
  detail: 'phase1-manual-operation'
}));
window.__PASI_NETWORK_INTERCEPTOR_HEALTH__();
```

The first Phase 1 acceptance target is transport truth: a real generation request must produce exactly one `STARTED` event and one terminal event (`COMPLETED`, `INTERRUPTED`, or `FAILED`) without changing the response delivered to ChatGPT.

Phase 1 does **not** yet route interceptor events into the bridge and does **not** remove the DOM controller. Those changes belong only after the transport observer is independently validated.
