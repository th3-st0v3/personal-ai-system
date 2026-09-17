# PASI Read-Only VS Code Integration

This optional VS Code extension publishes a small, bounded state document for PASI to consume.

It reports only:

- workspace folder names,
- active and visible editor paths relative to the workspace,
- language IDs,
- dirty state and cursor line,
- diagnostic counts by severity.

It does not read editor contents, selections, environment variables, terminals, credentials, or arbitrary files. It does not create terminals, run commands, or write project source files.

The state document is written atomically to:

```text
.runtime/computer/vscode-state.json
```

The PASI gateway treats the document as untrusted evidence and rejects missing, invalid, or stale state. Local runtime state is not part of the Git repository source-of-truth.

## Install

Open the repository in VS Code, choose **Run and Debug** only after the extension is packaged/installed according to the project's operator documentation, or use the extension-development workflow for testing.

This extension intentionally has no npm runtime dependencies and uses the VS Code extension API plus Node's built-in `fs` and `path` modules.

## Security boundary

This integration is a read-only observation adapter. Future write, terminal, process, application, or desktop capabilities must not be added to this extension directly. Those capabilities belong behind PASI's named capability and authorization layers.
