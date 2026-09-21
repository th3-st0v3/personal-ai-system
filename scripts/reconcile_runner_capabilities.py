#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
DEFAULT_SPEC = Path(__file__).resolve().parents[1] / "config" / "runner" / "capabilities.json"
DEFAULT_REPORT = Path.home() / ".pasi" / "runner" / "capabilities.json"
MAX_SPEC_BYTES = 128_000
MAX_REPORT_BYTES = 256_000


class CapabilityError(RuntimeError):
    pass


def load_spec(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_SPEC_BYTES:
            raise CapabilityError("capability spec is too large")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"could not read capability spec: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise CapabilityError("unsupported capability spec")
    if not isinstance(raw.get("resource_boundary"), dict):
        raise CapabilityError("resource_boundary must be an object")
    if not isinstance(raw.get("required_commands"), dict):
        raise CapabilityError("required_commands must be an object")
    if not isinstance(raw.get("required_system_packages"), list):
        raise CapabilityError("required_system_packages must be a list")
    return raw


def version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    return tuple(int(part or 0) for part in match.groups()) if match else ()


def command_version(command: str) -> str:
    path = shutil.which(command)
    if not path:
        return ""
    try:
        result = subprocess.run([path, "--version"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0][:300] if text else ""


def read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            fields = value.strip().split()
            if fields and fields[0].isdigit():
                result[key] = int(fields[0]) * 1024
    except OSError:
        pass
    return result


def resource_snapshot() -> dict[str, Any]:
    mem = read_meminfo()
    version_text = ""
    try:
        version_text = Path("/proc/version").read_text(encoding="utf-8")[:2000]
    except OSError:
        pass
    total_bytes = mem.get("MemTotal", 0)
    available_bytes = mem.get("MemAvailable", total_bytes)
    return {
        "cpu_count": os.cpu_count() or 0,
        "memory_mib": int(total_bytes / 1024 / 1024),
        "memory_available_mib": int(available_bytes / 1024 / 1024),
        "memory_used_mib": max(0, int((total_bytes - available_bytes) / 1024 / 1024)),
        "swap_mib": int(mem.get("SwapTotal", 0) / 1024 / 1024),
        "wsl_detected": "microsoft" in version_text.casefold() or "wsl" in version_text.casefold(),
        "architecture": platform.machine(),
        "system": platform.system(),
        "release": platform.release(),
    }


def package_installed(name: str) -> bool:
    if not shutil.which("dpkg-query"):
        return False
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "install ok installed" in result.stdout


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


def service_health(url: str) -> dict[str, Any]:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read(32_000).decode("utf-8"))
        return {"ok": isinstance(payload, dict), "status": getattr(response, "status", 200)}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)[:300]}


def detect(spec: Mapping[str, Any]) -> dict[str, Any]:
    resources = resource_snapshot()
    command_report: dict[str, Any] = {}
    command_failures: list[str] = []
    for command, minimum in spec.get("required_commands", {}).items():
        path = shutil.which(command)
        version = command_version(command)
        parsed = version_tuple(version)
        minimum = minimum if isinstance(minimum, Mapping) else {}
        min_major = int(minimum.get("min_major", 0))
        min_minor = int(minimum.get("min_minor", 0))
        version_ok = not min_major or (bool(parsed) and parsed >= (min_major, min_minor))
        ok = bool(path) and version_ok
        command_report[command] = {"path": path or "", "version": version, "version_ok": version_ok, "ok": ok}
        if not ok:
            command_failures.append(command)

    module_report = {
        str(name): module_available(str(name))
        for name in spec.get("required_python_modules", [])
        if isinstance(name, str)
    }
    module_failures = sorted(name for name, ok in module_report.items() if not ok)

    package_report = {
        str(name): package_installed(str(name))
        for name in spec.get("required_system_packages", [])
        if isinstance(name, str)
    }
    package_failures = sorted(name for name, ok in package_report.items() if not ok)

    runtime = spec.get("runtime_checks", {})
    bridge_url = runtime.get("bridge_health_url") if isinstance(runtime, Mapping) else None
    browser_url = runtime.get("browser_health_url") if isinstance(runtime, Mapping) else None
    bridge_health = service_health(bridge_url) if isinstance(bridge_url, str) else {"ok": False, "not_configured": True}
    browser_health = service_health(browser_url) if isinstance(browser_url, str) else {"ok": False, "not_configured": True}

    boundary = spec["resource_boundary"]
    boundary_failures: list[str] = []
    if resources["memory_mib"] > int(boundary["max_memory_mib"]):
        boundary_failures.append("memory")
    if resources["cpu_count"] > int(boundary["max_cpu_count"]):
        boundary_failures.append("cpu_count")
    if resources["swap_mib"] > int(boundary["max_swap_mib"]):
        boundary_failures.append("swap")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_name": os.environ.get("RUNNER_NAME", ""),
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "resources": resources,
        "boundary": boundary,
        "commands": command_report,
        "python_modules": module_report,
        "system_packages": package_report,
        "runtime": {"bridge_health": bridge_health, "browser_health": browser_health},
        "required_ok": not command_failures and not module_failures and not package_failures and not boundary_failures,
        "failures": {
            "commands": command_failures,
            "python_modules": module_failures,
            "system_packages": package_failures,
            "resource_boundary": boundary_failures,
        },
        "recommended_labels": list(spec.get("runner_labels", [])),
    }


def run(command: list[str], *, timeout: int = 900) -> tuple[int, str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return result.returncode, ((result.stdout or "") + (result.stderr or ""))[-12_000:]


def reconcile(spec: Mapping[str, Any], *, apply: bool, apply_optional: bool) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    initial = detect(spec)

    if apply and initial["failures"]["system_packages"]:
        missing = initial["failures"]["system_packages"]
        if not shutil.which("apt-get") or not shutil.which("sudo"):
            actions.append({"action": "install_system_packages", "ok": False, "packages": missing, "error": "sudo/apt-get unavailable"})
        else:
            code, output = run(["sudo", "-n", "apt-get", "update"])
            if code == 0:
                code, install_output = run(["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", *missing])
                actions.append({"action": "install_system_packages", "ok": code == 0, "packages": missing, "output": install_output[-4000:]})
            else:
                actions.append({"action": "install_system_packages", "ok": False, "packages": missing, "output": output[-4000:]})

    if apply and initial["failures"]["python_modules"]:
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        if requirements.is_file():
            code, output = run([sys.executable, "-m", "pip", "install", "-r", str(requirements)], timeout=1800)
            actions.append({"action": "install_python_requirements", "ok": code == 0, "output": output[-4000:]})
        else:
            actions.append({"action": "install_python_requirements", "ok": False, "error": "requirements.txt not found"})

    if apply_optional:
        optional = spec.get("optional_tools", {})
        ollama = optional.get("ollama") if isinstance(optional, Mapping) else None
        model = ollama.get("model") if isinstance(ollama, Mapping) else None
        if isinstance(model, str) and model and shutil.which("ollama"):
            code, output = run(["ollama", "pull", model], timeout=3600)
            actions.append({"action": "pull_ollama_model", "ok": code == 0, "model": model, "output": output[-4000:]})

    final = detect(spec)
    final["actions"] = actions
    return final


def write_report(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise CapabilityError("capability report is too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and reconcile PASI self-hosted runner capabilities.")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        spec = load_spec(args.spec.resolve())
        payload = reconcile(spec, apply=args.apply, apply_optional=args.apply_optional)
        write_report(args.report.expanduser().resolve(), payload)
    except CapabilityError as exc:
        print(f"CAPABILITY_RECONCILE_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        failures = payload["failures"]
        print(
            f"runner={payload['runner_name'] or '<local>'} required_ok={payload['required_ok']} "
            f"static_failures={sum(len(value) for value in failures.values())}"
        )
        for action in payload.get("actions", []):
            print(json.dumps(action, ensure_ascii=False))
    return 0 if payload["required_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
