# Conditional Tampermonkey Self-Update (Deprecated)

This document describes a retired compatibility architecture. PASI's supported browser-control path is now the native Chromium extension under `automation/chromium/pasi-chatgpt`.

The Tampermonkey controller loader and conditional self-update pipeline are migration-only artifacts for historical installations. They are not required by the PASI runner, the authenticated bridge, browser observation, or the 168-hour launcher.

Do not use this architecture for new installations. Native Chromium controller updates must follow the repository's normal source review, validation, version, and integrity checks.

The legacy Tampermonkey distribution service and its local release endpoints are retired. The deprecated loader remains only as a visible migration notice so older installations do not silently appear healthy.

## Migration

1. Disable or remove the legacy Tampermonkey controller and loader.
2. Install and enable `automation/chromium/pasi-chatgpt` as the native Chromium extension.
3. Verify `http://127.0.0.1:8765/health` and authenticated browser health.
4. Confirm browser observation reports `native_controller: true` and the expected native controller version.

Future controller changes are shipped through the native extension source and normal repository verification rather than through the retired Tampermonkey distribution flow.
