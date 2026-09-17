from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONTROLLER_PATH = Path("automation/tampermonkey/chatgpt-controller.user.js")
UPDATE_DIRECTIVE = re.compile(r"^\s*PASI_CONTROLLER_UPDATE\s*:\s*(true|false)\s*$", re.IGNORECASE | re.MULTILINE)
UPDATE_VERSION = re.compile(r"^\s*PASI_CONTROLLER_UPDATE_VERSION\s*:\s*([^\s]+)\s*$", re.IGNORECASE | re.MULTILINE)
UPDATE_REASON = re.compile(r"^\s*PASI_CONTROLLER_UPDATE_REASON\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
CONTROLLER_VERSION = re.compile(r"^//\s*@version\s+([^\s]+)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ControllerUpdateDecision:
    requested: bool
    version: str | None
    reason: str
    current_version: str | None
    last_synced_version: str | None
    eligible: bool
    state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_controller_update_directive(response_text: str) -> tuple[bool, str | None, str]:
    """Parse an explicit model signal; ordinary model output never requests an update."""
    if not isinstance(response_text, str):
        return False, None, ""

    match = UPDATE_DIRECTIVE.search(response_text)
    if match is None or match.group(1).lower() != "true":
        return False, None, ""

    version_match = UPDATE_VERSION.search(response_text)
    reason_match = UPDATE_REASON.search(response_text)
    version = version_match.group(1).strip() if version_match else None
    reason = reason_match.group(1).strip() if reason_match else "Explicit controller update requested."
    return True, version, reason[:2000]


def read_controller_version(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = CONTROLLER_VERSION.search(text)
    return match.group(1).strip() if match else None


def evaluate_controller_update(
    response_text: str,
    *,
    controller_path: Path,
    last_synced_version: str | None,
) -> ControllerUpdateDecision:
    requested, requested_version, reason = parse_controller_update_directive(response_text)
    current_version = read_controller_version(controller_path)

    if not requested:
        return ControllerUpdateDecision(
            requested=False,
            version=None,
            reason="",
            current_version=current_version,
            last_synced_version=last_synced_version,
            eligible=False,
            state="no_request",
        )

    if requested_version is None:
        return ControllerUpdateDecision(
            requested=True,
            version=None,
            reason=reason,
            current_version=current_version,
            last_synced_version=last_synced_version,
            eligible=False,
            state="missing_version",
        )

    if current_version is None or requested_version != current_version:
        return ControllerUpdateDecision(
            requested=True,
            version=requested_version,
            reason=reason,
            current_version=current_version,
            last_synced_version=last_synced_version,
            eligible=False,
            state="source_version_mismatch",
        )

    if last_synced_version == current_version:
        return ControllerUpdateDecision(
            requested=True,
            version=requested_version,
            reason=reason,
            current_version=current_version,
            last_synced_version=last_synced_version,
            eligible=False,
            state="already_synced",
        )

    return ControllerUpdateDecision(
        requested=True,
        version=requested_version,
        reason=reason,
        current_version=current_version,
        last_synced_version=last_synced_version,
        eligible=True,
        state="ready",
    )


def write_update_request(path: Path, decision: ControllerUpdateDecision, *, source: str) -> None:
    if not decision.eligible or decision.current_version is None:
        raise ValueError("controller update decision is not eligible")
    payload = {
        "schema_version": "1",
        "source": source,
        "controller_path": str(CONTROLLER_PATH),
        "requested_version": decision.current_version,
        "reason": decision.reason,
        "state": "ready",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_last_synced_version(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("last_synced_version")
    return value if isinstance(value, str) and value.strip() else None


def write_sync_state(path: Path, *, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": "1", "last_synced_version": version},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


__all__ = [
    "CONTROLLER_PATH",
    "ControllerUpdateDecision",
    "evaluate_controller_update",
    "parse_controller_update_directive",
    "read_controller_version",
    "read_last_synced_version",
    "write_sync_state",
    "write_update_request",
]
