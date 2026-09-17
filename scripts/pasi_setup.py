from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from automation.computer_use.setup_requirements import MARKDOWN_RELATIVE_PATH, RUNTIME_RELATIVE_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "config" / "automation" / "setup_catalog.json"
BRIDGE_URL = "http://127.0.0.1:8765"
CONTROLLER_URL = "http://127.0.0.1:8766"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _runtime_observation() -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/browser/observation", timeout=3.0) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    observation = payload.get("observation") if isinstance(payload, dict) else None
    return observation if isinstance(observation, dict) else None


def _health(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            payload = json.loads(response.read(100_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_dynamic() -> dict[str, Any]:
    dynamic_path = REPO_ROOT / RUNTIME_RELATIVE_PATH
    return _load_json(dynamic_path)


def _entries(catalog: dict[str, Any], dynamic: dict[str, Any], key: str) -> list[dict[str, Any]]:
    baseline = catalog.get(key, [])
    extra = dynamic.get(key, [])
    merged: list[dict[str, Any]] = []
    for item in list(baseline) + list(extra):
        if isinstance(item, dict):
            merged.append(item)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in merged:
        identity = (
            str(item.get("name", "")).casefold(),
            str(item.get("url", item.get("source", ""))).casefold(),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
    return unique


def build_report() -> dict[str, Any]:
    catalog = _load_json(CATALOG_PATH)
    dynamic = _merge_dynamic()
    downloads = _entries(catalog, dynamic, "downloads")
    logins = _entries(catalog, dynamic, "logins")
    python_path = REPO_ROOT / ".venv" / "bin" / "python"
    observation = _runtime_observation()
    bridge_health = _health(BRIDGE_URL + "/health")
    controller_health = _health(CONTROLLER_URL + "/health")
    runtime_data: dict[str, Any] = {}
    if observation is not None:
        observed_data = observation.get("data")
        if isinstance(observed_data, dict):
            runtime_data = observed_data
    return {
        "repository": str(REPO_ROOT),
        "local_prerequisites": {
            "venv_python": {
                "path": str(python_path),
                "present": python_path.is_file(),
                "executable": python_path.is_file() and python_path.stat().st_mode & 0o111 != 0,
            },
            "git": {"present": shutil.which("git") is not None},
            "node": {"present": shutil.which("node") is not None},
        },
        "runtime": {
            "bridge_health": bridge_health or {"status": "unavailable"},
            "controller_distribution_health": controller_health or {"status": "unavailable"},
            "browser_observation": observation or {"status": "unavailable"},
            "chatgpt_login_required": runtime_data.get("auth_required") is True,
            "chatgpt_usage_limited": runtime_data.get("provider_usage_limited") is True,
            "chatgpt_context_exhausted": runtime_data.get("conversation_context_exhausted") is True,
        },
        "downloads": downloads,
        "logins": logins,
        "dynamic_requirements_file": str(REPO_ROOT / RUNTIME_RELATIVE_PATH),
        "dynamic_requirements_markdown": str(REPO_ROOT / MARKDOWN_RELATIVE_PATH),
        "verification_policy": "PASI never bypasses CAPTCHA, Cloudflare, MFA, security checks, or credential prompts. Complete interactive checks manually and keep the authenticated browser session available.",
    }


def print_report(report: dict[str, Any]) -> None:
    print("=== PASI SETUP / PREFLIGHT ===")
    print(f"Repository: {report['repository']}")
    print()
    print("Required downloads")
    required_downloads = [item for item in report["downloads"] if item.get("required") is True]
    optional_downloads = [item for item in report["downloads"] if item.get("required") is not True]
    for item in required_downloads:
        version = f" [{item.get('version')}]" if item.get("version") else ""
        print(f"  [REQUIRED] {item.get('name', 'unnamed')}{version} — {item.get('reason', '')}")
    if not required_downloads:
        print("  None recorded.")
    print()
    print("Conditional / optional downloads")
    for item in optional_downloads:
        version = f" [{item.get('version')}]" if item.get("version") else ""
        print(f"  [CONDITIONAL] {item.get('name', 'unnamed')}{version} — {item.get('reason', '')}")
    if not optional_downloads:
        print("  None recorded.")
    print()
    print("Websites requiring a prepared login")
    for item in report["logins"]:
        level = "REQUIRED" if item.get("required") is True else "CONDITIONAL"
        print(f"  [{level}] {item.get('name', 'unnamed')} — {item.get('url', '')}")
        print(f"      Verification: {item.get('verification', 'login')} — {item.get('reason', '')}")
    print()
    print("Local prerequisites")
    for name, value in report["local_prerequisites"].items():
        state = "OK" if value.get("present") and (value.get("executable", True)) else "MISSING"
        print(f"  [{state}] {name}")
    print()
    print("Runtime")
    bridge = report["runtime"]["bridge_health"].get("status", "unavailable")
    distribution = report["runtime"]["controller_distribution_health"].get("status", "unavailable")
    print(f"  Bridge: {bridge}")
    print(f"  Controller distribution: {distribution}")
    if report["runtime"]["chatgpt_login_required"]:
        print("  ChatGPT: ACTION REQUIRED — authenticate / complete the interactive security check in the browser.")
    elif report["runtime"]["chatgpt_usage_limited"]:
        print("  ChatGPT: provider/account usage limit detected; PASI will use configured fallbacks when possible.")
    elif report["runtime"]["chatgpt_context_exhausted"]:
        print("  ChatGPT: current conversation is exhausted; PASI recovery will use a fresh chat.")
    else:
        print("  ChatGPT: no authentication or usage-limit obstacle is currently reported.")
    print()
    print(report["verification_policy"])
    print(f"\nDynamic requirement JSON: {report['dynamic_requirements_file']}")
    print(f"Dynamic requirement checklist: {report['dynamic_requirements_markdown']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show and validate PASI unattended automation setup requirements.")
    parser.add_argument("--check", action="store_true", help="return non-zero when mandatory local prerequisites are missing")
    parser.add_argument("--json", action="store_true", help="print the machine-readable setup report")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)

    mandatory = report["local_prerequisites"]["venv_python"]
    git = report["local_prerequisites"]["git"]
    if args.check and (not mandatory.get("present") or not mandatory.get("executable") or not git.get("present")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
