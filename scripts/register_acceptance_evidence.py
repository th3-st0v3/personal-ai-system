#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = Path.home() / ".pasi" / "acceptance" / "registry.jsonl"
MANIFEST = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class EvidenceRegistryError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceRegistryError(f"evidence artifact not found: {path}")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise EvidenceRegistryError(f"evidence artifact is too large: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceRegistryError(f"could not parse evidence artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise EvidenceRegistryError(f"evidence artifact must contain a JSON object: {path}")
    return payload


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRegistryError("could not read repository HEAD") from exc
    head = result.stdout.strip()
    if result.returncode != 0 or not head:
        raise EvidenceRegistryError("repository HEAD is unavailable")
    return head


def _controller_version() -> str:
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceRegistryError(f"could not read native controller manifest: {MANIFEST}") from exc
    version = str(payload.get("version", "")).strip()
    if not version:
        raise EvidenceRegistryError("native controller manifest has no version")
    return version


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _identity(payload: Mapping[str, Any], key: str, env_key: str, override: str) -> str:
    value = override.strip() or str(payload.get(key, "")).strip() or os.environ.get(env_key, "").strip()
    return value


def build_record(
    artifact: Path,
    payload: Mapping[str, Any],
    *,
    code_head: str,
    run_id: str,
    task_id: str,
    provider: str,
) -> dict[str, Any]:
    gate = str(payload.get("gate", "")).strip().upper()
    status = str(payload.get("status", "")).strip().upper()
    if not gate:
        raise EvidenceRegistryError(f"evidence artifact has no gate: {artifact}")
    if status != "PASS":
        raise EvidenceRegistryError(f"evidence artifact is not a PASS: {artifact}")
    resolved_code_head = code_head.strip() or str(payload.get("code_head", "")).strip()
    if not resolved_code_head:
        resolved_code_head = str(payload.get("commit", "")).strip()
    if not resolved_code_head:
        raise EvidenceRegistryError(
            f"evidence artifact has no exact code head: {artifact}; pass --code-head when the artifact does not record one"
        )
    resolved_run_id = _identity(payload, "run_id", "PASI_RUN_ID", run_id)
    resolved_task_id = _identity(payload, "task_id", "PASI_TASK_ID", task_id)
    if not resolved_run_id:
        operation_id = str(payload.get("operation_id", "")).strip()
        resolved_run_id = operation_id
    if not resolved_task_id:
        resolved_task_id = gate
    resolved_provider = (
        provider.strip()
        or str(payload.get("provider", "")).strip()
        or os.environ.get("PASI_PRIMARY_PROVIDER", "").strip()
        or "chatgpt"
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "gate": gate,
        "status": status,
        "artifact": str(artifact.resolve()),
        "artifact_sha256": digest,
        "code_head": resolved_code_head,
        "controller_version": _controller_version(),
        "environment": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "runner_name": os.environ.get("RUNNER_NAME", "").strip(),
            "runner_labels": os.environ.get("RUNNER_LABELS", "").strip(),
            "github_repository": os.environ.get("GITHUB_REPOSITORY", "").strip(),
        },
        "provider": resolved_provider,
        "timestamps": {
            "started_at": _timestamp(payload.get("started_at")),
            "completed_at": _timestamp(payload.get("completed_at")),
            "registered_at": datetime.now(timezone.utc).isoformat(),
        },
        "identity": {
            "run_id": resolved_run_id,
            "task_id": resolved_task_id,
        },
    }


def _existing_digests(registry: Path) -> set[str]:
    if not registry.exists():
        return set()
    digests: set[str] = set()
    for line in registry.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            digest = str(item.get("artifact_sha256", "")).strip()
            if digest:
                digests.add(digest)
    return digests


def register(record: Mapping[str, Any], registry: Path) -> bool:
    registry = registry.expanduser().resolve()
    registry.parent.mkdir(parents=True, exist_ok=True)
    digest = str(record.get("artifact_sha256", "")).strip()
    if not digest:
        raise EvidenceRegistryError("registry record has no artifact digest")
    if digest in _existing_digests(registry):
        return False
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with registry.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a verified PASI live acceptance artifact.")
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--code-head", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--provider", default="")
    args = parser.parse_args()
    try:
        fallback_head = args.code_head.strip() or _git_head()
        for artifact in args.artifacts:
            path = artifact.expanduser().resolve()
            payload = _read_json(path)
            record = build_record(
                path, payload, code_head=fallback_head, run_id=args.run_id, task_id=args.task_id, provider=args.provider
            )
            added = register(record, args.registry)
            print(f"{'REGISTERED' if added else 'ALREADY_REGISTERED'} {path}")
    except EvidenceRegistryError as exc:
        print(f"ACCEPTANCE_REGISTRY_ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
