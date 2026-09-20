# Conditional Tampermonkey Self-Update

PASI does not update its ChatGPT browser controller after every model response.

The controller update path is deliberately conditional:

1. ChatGPT is instructed to emit an explicit three-line controller-update signal only when the controller itself needs a code change:
   - `PASI_CONTROLLER_UPDATE: true`
   - `PASI_CONTROLLER_UPDATE_VERSION: <exact controller @version>`
   - `PASI_CONTROLLER_UPDATE_REASON: <technical reason>`
2. `automation/legacy/controller_update.py` parses the signal and refuses to stage an update when the signal is missing, false, missing a version, mismatched with the source version, or already synchronized.
3. The launcher writes a bounded local update request under `.runtime/chatgpt/controller-update-request.json` when the request is eligible.
4. A controller change is still developed and tested like normal PASI code. The model signal is a trigger, not permission to execute arbitrary code.
5. After the controller change is merged to `main`, `scripts/publish_controller_release.py` can publish a versioned `automation/legacy/tampermonkey/controller-sync.json` manifest containing the controller SHA-256 digest.
6. The one-time-installed `automation/legacy/tampermonkey/chatgpt-controller-loader.user.js` checks that manifest. It only loads a controller when `enabled` is true and the published version/hash differ from its last verified release.
7. Before execution, the loader restricts the source URL to this repository's `main` raw GitHub path and verifies the downloaded controller against the manifest SHA-256 digest.

## One-time browser setup

Install `chatgpt-controller-loader.user.js` in Tampermonkey and disable the older directly-installed ChatGPT controller so the two controllers do not poll the bridge simultaneously. The loader then becomes the stable browser-side bootstrap; future controller changes are delivered through the versioned release manifest.

Tampermonkey supports `@updateURL` and `@downloadURL`, but the PASI loader uses its own explicit release manifest so a normal ChatGPT response cannot directly cause a script replacement. Tampermonkey's current documentation requires an `@version` tag for update checks and documents `@updateURL` / `@downloadURL`; this PASI design adds an application-level gate and digest verification on top. 

## Failure behavior

A missing directive means no update. A false directive means no update. A malformed or mismatched version means no update. A repeated request for the already-synchronized version means no update. A manifest with an invalid source URL or invalid digest is rejected. A downloaded controller whose SHA-256 does not match the manifest is never executed.
