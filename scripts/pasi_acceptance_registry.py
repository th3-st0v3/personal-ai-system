#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _controller_version(root: Path) -> str | None:
    source = root / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"\bconst\s+CONTROLLER_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    return match.group(1).strip() if match else None


def _manifest_version(root: Path) -> str | None:
    path = root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("version")
    return str(value) if value is not None else None


def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_identity(payload: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for key in (
        "operation_id",
        "task_id",
        "session_id",
        "run_id",
        "runner_run_id",
        "repository",
        "branch",
        "commit",
        "base_commit",
        "authenticated_browser_chat_url",
        "chat_url",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            identity[key] = value

    results = payload.get("results")
    if isinstance(results, list):
        operation_ids = [
            item.get("operation_id")
            for item in results
            if isinstance(item, dict) and isinstance(item.get("operation_id"), str)
        ]
        if operation_ids:
            identity["operation_ids"] = operation_ids

    return identity


def build_entry(artifact: Path, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    recorded_commit = payload.get("commit")
    commit = (
        recorded_commit
        if isinstance(recorded_commit, str) and re.fullmatch(r"[0-9a-f]{40}", recorded_commit)
        else os.environ.get("GITHUB_SHA") or "unknown"
    )
    recorded_branch = payload.get("branch")
    branch = (
        str(recorded_branch)
        if isinstance(recorded_branch, str) and recorded_branch.strip()
        else os.environ.get("GITHUB_REF_NAME") or "unknown"
    )
    provider = payload.get("provider")
    completed_at = payload.get("completed_at")

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": {
            "path": str(artifact.resolve()),
            "sha256": _artifact_sha256(artifact),
            "size_bytes": artifact.stat().st_size,
        },
        "gate": str(payload.get("gate") or "unknown"),
        "status": str(payload.get("status") or "unknown"),
        "code": {
            "repository": (
                str(payload.get("repository")).strip()
                if isinstance(payload.get("repository"), str) and str(payload.get("repository")).strip()
                else os.environ.get("GITHUB_REPOSITORY") or "unknown"
            ),
            "head_commit": commit,
            "branch": branch,
        },
        "controller": {
            "content_version": _controller_version(root),
            "manifest_version": _manifest_version(root),
        },
        "environment": {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "runner_name": os.environ.get("RUNNER_NAME") or os.environ.get("HOSTNAME"),
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "runner_arch": os.environ.get("RUNNER_ARCH") or platform.machine(),
            "python_version": platform.python_version(),
        },
        "provider": provider if isinstance(provider, str) else None,
        "timestamps": {
            "artifact_completed_at": completed_at,
        },
        "identity": _artifact_identity(payload),
    }


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("acceptance registry must contain a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def write_registry(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def _resolve_gate_artifact(root: Path, gate: str) -> Path:
    acceptance_dir = root / ".runtime" / "acceptance"
    if gate == "M0":
        return acceptance_dir / "m0-live.json"
    if gate == "M1":
        return acceptance_dir / "m1-live.json"
    if gate == "M2":
        candidates = sorted(acceptance_dir.glob("m2-live-*.json"))
        if not candidates:
            raise FileNotFoundError("no M2 acceptance artifact exists")
        return candidates[-1]
    raise ValueError(f"unsupported live acceptance gate: {gate}")


def _record_artifact(
    artifact: Path,
    output: Path,
    root: Path,
) -> dict[str, Any]:
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance artifact must contain a JSON object")

    entry = build_entry(artifact, root, payload)
    entries = load_registry(output)

    key = (entry["artifact"]["sha256"], entry["artifact"]["path"])
    for existing in entries:
        existing_artifact = existing.get("artifact")
        if isinstance(existing_artifact, dict) and (
            existing_artifact.get("sha256"),
            existing_artifact.get("path"),
        ) == key:
            return existing

    entries.append(entry)
    write_registry(output, entries)
    return entry


def record_gate(
    gate: str,
    output: Path | None = None,
    *,
    _root_for_test: Path | None = None,
) -> dict[str, Any]:
    root = (_root_for_test or Path(__file__).resolve().parents[1]).resolve()
    artifact = _resolve_gate_artifact(root, gate)
    registry = output or (Path.home() / ".pasi" / "acceptance" / "registry.json")
    return _record_artifact(artifact.resolve(), registry, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record durable PASI live-acceptance evidence.")
    parser.add_argument("gate", choices=("M0", "M1", "M2"))
    args = parser.parse_args()

    entry = record_gate(args.gate)
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
