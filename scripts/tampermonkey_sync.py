from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from automation.orchestrator.controller_update import (
    evaluate_controller_update,
    read_last_synced_version,
    write_sync_state,
    write_update_request,
)

RUNTIME_DIR = REPOSITORY_ROOT / ".runtime" / "chatgpt"
DEFAULT_REQUEST_PATH = RUNTIME_DIR / "controller-update-request.json"
DEFAULT_STATE_PATH = RUNTIME_DIR / "controller-sync-state.json"
DEFAULT_CONTROLLER_PATH = REPOSITORY_ROOT / "automation" / "tampermonkey" / "chatgpt-controller.user.js"


def stage_from_response(response_text: str, controller_path: Path, request_path: Path, state_path: Path) -> int:
    decision = evaluate_controller_update(
        response_text,
        controller_path=controller_path,
        last_synced_version=read_last_synced_version(state_path),
    )
    print(json.dumps(decision.to_dict(), indent=2, ensure_ascii=False))
    if not decision.eligible:
        return 0
    write_update_request(request_path, decision, source="sync-cli")
    print(f"READY: controller update request staged at {request_path}")
    return 0


def mark_synced(version: str, state_path: Path, request_path: Path) -> int:
    if not version.strip():
        raise ValueError("version is required")
    write_sync_state(state_path, version=version.strip())
    try:
        request_path.unlink()
    except FileNotFoundError:
        pass
    print(f"SYNCED: Tampermonkey controller version {version.strip()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Conditionally stage and acknowledge PASI Tampermonkey controller synchronization.")
    parser.add_argument("--response-file", type=Path, help="ChatGPT response file to inspect for the explicit controller-update directive")
    parser.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER_PATH)
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--mark-synced", metavar="VERSION", help="Record a verified installed controller version and clear the pending request")
    args = parser.parse_args()

    if args.mark_synced:
        return mark_synced(args.mark_synced, args.state, args.request)
    if args.response_file is None:
        parser.error("--response-file or --mark-synced is required")

    response_text = args.response_file.read_text(encoding="utf-8")
    return stage_from_response(response_text, args.controller, args.request, args.state)


if __name__ == "__main__":
    raise SystemExit(main())
