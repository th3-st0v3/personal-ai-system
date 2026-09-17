from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = REPOSITORY_ROOT / "automation" / "tampermonkey" / "chatgpt-controller.user.js"
MANIFEST_PATH = REPOSITORY_ROOT / "automation" / "tampermonkey" / "controller-sync.json"
REQUEST_PATH = REPOSITORY_ROOT / ".runtime" / "chatgpt" / "controller-update-request.json"


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_version() -> str:
    for line in CONTROLLER_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("// @version"):
            parts = stripped.split()
            if len(parts) == 3 and parts[2]:
                return parts[2]
    raise ValueError("controller @version was not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a verified PASI controller version to the conditional sync manifest.")
    parser.add_argument("--allow-non-main", action="store_true", help="Allow publishing while not checked out on main")
    args = parser.parse_args()

    if not CONTROLLER_PATH.is_file():
        raise SystemExit("error: controller source is missing")
    if not REQUEST_PATH.is_file():
        raise SystemExit("error: no explicit controller update request is staged")
    if not args.allow_non_main and run(["git", "branch", "--show-current"]) != "main":
        raise SystemExit("error: controller release must be prepared from main after the controller change is merged")
    if run(["git", "status", "--short"]):
        raise SystemExit("error: working tree must be clean before publishing controller release")

    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: invalid controller update request: {exc}")
    if not isinstance(request, dict) or request.get("state") != "ready":
        raise SystemExit("error: controller update request is not ready")

    version = read_version()
    requested_version = request.get("requested_version")
    if requested_version != version:
        raise SystemExit("error: staged request version does not match controller source version")

    source = CONTROLLER_PATH.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    commit = run(["git", "rev-parse", "HEAD"])
    reason = request.get("reason") if isinstance(request.get("reason"), str) else "Explicit PASI controller update."

    manifest = {
        "schema_version": "1",
        "enabled": True,
        "version": version,
        "source_url": "https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/tampermonkey/chatgpt-controller.user.js",
        "sha256": digest,
        "release_commit": commit,
        "reason": reason[:2000],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"READY_TO_COMMIT: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
