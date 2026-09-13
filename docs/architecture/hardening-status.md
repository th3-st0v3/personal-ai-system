# Hardening status

## Deployment model

The current application is a **local-first beta application with a production-oriented security direction**. The supported baseline remains a single-process WSGI server with SQLite storage. The code should not be described as horizontally scalable production infrastructure yet.

The local browser endpoint remains `127.0.0.1:8000` unless the operator explicitly passes `--host` or `--port` to `scripts/serve_web.py`.

## What was fixed without intentionally removing capabilities

- Authentication sessions are persisted in SQLite instead of a process-global dictionary. Sessions expire, can be revoked, and support explicit token rotation.
- Concurrent logins remain valid. A new login does **not** silently log the user out of other devices; this avoids trading away multi-device behavior for a simpler security policy.
- Tool arguments and external source content have explicit size/type boundaries.
- Ingested sources are explicitly marked `untrusted`, retain checksums and source metadata, and expose chunk-level provenance.
- Authorization now records action decisions and applies persistent per-actor/action rate limits.
- The web boundary adds security headers and an origin check for state-changing API requests when an Origin header is supplied.
- Frontend runtime behavior gains a shared state/event surface and normalized HTTP error handling without replacing the existing UI modules.
- Provider configuration errors are explicit in the chat response metadata and model-backed `frontier` mode fails rather than silently converting a configuration error into a successful-looking model response.

## Important caveats

This branch does **not** claim that every architectural item in the audit is complete. The remaining work is deliberately visible rather than disguised:

1. The repository still has schema initialization responsibilities spread across `db.py`, `auth_service.py`, `chat_service.py`, `policy.py`, `engineering_schema.py`, and `workspace_storage.py`. A final migration registry should become the only runtime schema entry point.
2. The web API still needs a complete canonical request-schema layer so every endpoint validates the same way before domain calls.
3. The ingestion adapters for GitHub/PDF need the same provenance and size-policy enforcement as the text ingestion service, including file-format-specific budgets.
4. The UI remains split across several legacy scripts. The new runtime boundary is additive, but the state/rendering split is not yet a full rewrite.
5. A production deployment still needs an explicit process manager, HTTPS termination, secrets management, external session storage when SQLite is no longer sufficient, and operational telemetry.

These are tracked as technical debt rather than ignored failures. No capability was deleted merely to make the repository appear cleaner.

## Audit policy

Future changes should follow this rule: **do not convert an error into a fallback unless the fallback is an intentional, documented product behavior**. When a fallback is necessary for local/offline operation, expose its status to the caller so it cannot be mistaken for a successful production path.
