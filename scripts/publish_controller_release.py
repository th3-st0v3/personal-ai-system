from __future__ import annotations

import argparse
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


def load_request(request_path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: invalid controller update request: {exc}")
    if not isinstance(payload, dict) or payload.get("state") != "ready":
        raise SystemExit("error: controller update request is not ready")
    version = payload.get("requested_version")
    reason = payload.get("reason")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("error: controller update request has no requested version")
    return version.strip(), reason.strip()[:2000] if isinstance(reason, str) else "Explicit PASI controller update."


def git_blob_sha1(path: Path) -> str:
    digest = run(["git", "hash-object", str(path)])
    if len(digest) != 40 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise SystemExit("error: could not calculate controller Git blob SHA-1")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a verified PASI controller version to the conditional sync manifest.")
    parser.add_argument("--request", type=Path, default=REQUEST_PATH)
    parser.add_argument("--version", help="Explicit requested controller version when the transient runtime request is unavailable after a merge")
    parser.add_argument("--reason", default="Explicit PASI controller update.")
    parser.add_argument("--allow-non-main", action="store_true", help="Allow publishing while not checked out on main")
    args = parser.parse_args()

    if not CONTROLLER_PATH.is_file():
        raise SystemExit("error: controller source is missing")
    if not args.allow_non_main and run(["git", "branch", "--show-current"]) != "main":
        raise SystemExit("error: controller release must be prepared from main after the controller change is merged")
    if run(["git", "status", "--short"]):
        raise SystemExit("error: working tree must be clean before publishing controller release")

    if args.version:
        requested_version = args.version.strip()
        reason = args.reason.strip()[:2000]
    elif args.request.is_file():
        requested_version, reason = load_request(args.request)
    else:
        raise SystemExit("error: provide --version after merge or keep the local controller update request available")

    version = read_version()
    if requested_version != version:
        raise SystemExit("error: requested version does not match controller source version")

    git_blob_sha = git_blob_sha1(CONTROLLER_PATH)
    commit = run(["git", "rev-parse", "HEAD"])

    manifest = {
        "schema_version": "1",
        "enabled": True,
        "version": version,
        "source_url": "https://raw.githubusercontent.com/th3-st0v3/personal-ai-system/main/automation/legacy/tampermonkey/chatgpt-controller.user.js",
        "git_blob_sha": git_blob_sha,
        "release_commit": commit,
        "reason": reason,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"READY_TO_COMMIT: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
