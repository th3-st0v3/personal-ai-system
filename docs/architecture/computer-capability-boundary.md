# PASI Computer Capability Boundary

PASI is designed to become more integrated with the host computer incrementally. Integration grows by adding named capabilities behind one authorization boundary, not by giving an AI provider unrestricted shell or desktop access.

## Current safe layer

The provider-neutral capability gateway currently exposes:

- `computer.system.read` — bounded OS/runtime metadata.
- `computer.files.list` — directory listing inside explicitly approved roots.
- `computer.files.read` — bounded UTF-8 text reads inside explicitly approved roots.
- `computer.browser.chatgpt` — the provider-specific ChatGPT browser surface through the browser-controller boundary.
- `computer.ide.read` — reserved provider-neutral capability for an IDE adapter.

Local roots are intentionally limited. PASI always includes its repository root and can accept additional explicit roots through the `PASI_ALLOWED_ROOTS` environment variable. Relative paths resolve only within those roots, and resolved symlinks cannot escape them.

Secret-like files and repository metadata are not exposed by the local read broker. Examples include `.env*`, credential/secret names, SSH keys, and private key/container formats.

## Capability levels

### Observe

Read runtime state and bounded diagnostics. These operations may run automatically.

### Read

Read explicitly approved workspace content. Reads are bounded by size and path policy.

### Interact

Browser, IDE, application, and desktop interaction is a separate capability family. These actions must remain provider-specific and must pass the authorization policy before execution.

### Change

File writes, command execution, application launch, and other state-changing operations require explicit human authorization and an allowlisted execution adapter. The current local capability gateway does not execute them.

### Consequential

Credentials, financial execution, destructive actions, deployment, or equivalent high-impact operations are outside the unattended computer-use boundary.

## AI request protocol

A ChatGPT task can request safe local evidence with a bounded marker:

```text
PASI_COMPUTER_REQUEST_BEGIN
{"request_id":"read-1","capability":"computer.files.read","parameters":{"path":"README.md","max_chars":20000}}
PASI_COMPUTER_REQUEST_END
```

PASI executes only capabilities implemented by the gateway, returns the result as untrusted evidence, and lets the model continue the same conversation. A task may make at most three capability rounds, with at most three requests per round.

The model never receives credentials or unrestricted command execution through this mechanism.

## Dependency strategy

The core capability layer uses the Python standard library. It does not require Tampermonkey, browser automation SDKs, or a provider-specific agent framework.

The native Chromium extension is the preferred browser integration path. Tampermonkey remains a compatibility fallback while local validation is completed.

## Expansion rule

Every new computer capability should add:

1. a named capability and risk classification,
2. a single implementation behind the gateway,
3. path/input/size bounds appropriate to the capability,
4. deterministic tests for allowed and rejected cases,
5. a recovery path for interrupted actions,
6. explicit separation between safe automation and approval-required work.

Never add a catch-all `shell`, unrestricted filesystem, credential reader, or arbitrary desktop-control endpoint to bypass these layers.
