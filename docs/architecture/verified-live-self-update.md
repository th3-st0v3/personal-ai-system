# Verified Live Self-Update

PASI supports live browser-side adoption of controller and recovery improvements without executing an overnight feature branch directly.

## Trust boundary

The overnight runner works in a dedicated worktree/branch. Its model-proposed changes are constrained by patch-path validation and accepted only after deterministic repository verification. The runner may change WSL scripts, VS Code integration, Chromium/Tampermonkey automation, recovery, research, and tests, but the browser controller is not promoted directly from that branch.

The local controller distribution server is the promotion boundary. It refreshes the Git `origin/main` remote-tracking ref periodically with a read-only `git fetch`. Controller and recovery source are then loaded from the exact same `origin/main` commit, and the server calculates Git blob SHA-1 identities directly from those bytes. The browser receives the generated manifest only after both sources have been read successfully and size/version checks pass.

When the remote main ref cannot be refreshed, the server may use the local checkout only when it is a clean `main` branch and the existing signed-by-hash release manifest still verifies. A dirty or non-main checkout cannot become a live browser release through this fallback.

## Browser activation

The Tampermonkey loader polls the local distribution server. It verifies the controller blob and recovery blob independently against the server's manifest, tracks the active hashes, and reloads the page when either hash changes. It never accepts source merely because a version string changed.

This means the update sequence is:

`model proposal -> patch validation -> deterministic tests -> commit/push -> PR/merge to main -> origin/main refresh -> Git blob verification -> Tampermonkey reload`

The sequence deliberately excludes direct execution of feature-branch JavaScript.

## Recovery interaction

The native recovery companion remains part of the same verified release unit as the controller. A recovery-only change therefore invalidates the active recovery hash and causes a clean browser reload too. This prevents an old recovery policy from remaining resident indefinitely after a verified main-branch update.

## Free-first behavior

No paid model API is required for this promotion mechanism. It uses Git, the local PASI server, the existing browser session, and the normal GitHub merge path. Optional model providers can help generate improvements, but they are not part of the trust anchor.

## Operational requirement

The WSL repository must have a working `origin` remote with permission to fetch `main`. The server uses Git's normal credential configuration and does not read or transmit passwords, browser cookies, or session tokens.
