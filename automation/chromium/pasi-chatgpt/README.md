# PASI Native ChatGPT Controller

This is the native Chromium replacement for the PASI Tampermonkey controller.

## Install

Open `chrome://extensions` in Chromium or Chrome, enable **Developer mode**, choose **Load unpacked**, and select this directory:

`automation/chromium/pasi-chatgpt`

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
