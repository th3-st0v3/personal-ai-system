#!/usr/bin/env python3
"""Attach PASI to an already-running Chromium-family browser through CDP."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.e2e_chromium_response_recovery import BrowserCdpClient


def candidate_ports() -> list[int]:
    return list(range(9222, 9231)) + [9515, 9229]


def browser_endpoint(port: int) -> str | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version",
            timeout=1.5,
        ) as response:
            payload = json.loads(response.read(200_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    value = payload.get("webSocketDebuggerUrl")
    return value if isinstance(value, str) and value else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attach PASI to an already-running browser only"
    )
    parser.add_argument("--extension-dir", required=True, type=Path)
    args = parser.parse_args()

    extension_dir = args.extension_dir.expanduser().resolve()
    manifest = json.loads(
        (extension_dir / "manifest.json").read_text(encoding="utf-8")
    )
    expected_name = str(manifest.get("name") or "PASI ChatGPT Controller")
    expected_version = str(manifest.get("version") or "")

    endpoints = []
    for port in candidate_ports():
        endpoint = browser_endpoint(port)
        if endpoint:
            endpoints.append((port, endpoint))

    if not endpoints:
        print("PASI existing-browser attach: no browser DevTools endpoint detected")
        return 2

    errors: list[str] = []
    for port, endpoint in endpoints:
        cdp = None
        try:
            cdp = BrowserCdpClient(endpoint)
            installed = cdp.command("Extensions.getExtensions", timeout=10)
            extensions = installed.get("extensions", [])

            if isinstance(extensions, list):
                for entry in extensions:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("name") != expected_name:
                        continue
                    version = str(entry.get("version") or "")
                    extension_id = str(entry.get("id") or "")
                    if version == expected_version:
                        print(
                            "PASI existing-browser attach: controller already loaded "
                            + extension_id
                            + " version="
                            + version
                            + " port="
                            + str(port)
                        )
                        return 0
                    raise RuntimeError(
                        "existing PASI controller version "
                        + version
                        + " differs from expected "
                        + expected_version
                    )

            loaded = cdp.command(
                "Extensions.loadUnpacked",
                {"path": str(extension_dir)},
                timeout=20,
            )
            extension_id = loaded.get("id")
            if not isinstance(extension_id, str) or not extension_id:
                raise RuntimeError(
                    "Extensions.loadUnpacked returned no extension id: "
                    + repr(loaded)
                )

            verified = cdp.command("Extensions.getExtensions", timeout=10)
            verified_extensions = verified.get("extensions", [])
            if not any(
                isinstance(item, dict) and item.get("id") == extension_id
                for item in (
                    verified_extensions
                    if isinstance(verified_extensions, list)
                    else []
                )
            ):
                raise RuntimeError(
                    "loaded extension was not visible in Extensions.getExtensions"
                )

            print(
                "PASI existing-browser attach: loaded PASI controller version="
                + expected_version
                + " id="
                + extension_id
                + " port="
                + str(port)
            )
            return 0
        except Exception as exc:
            errors.append("port " + str(port) + ": " + str(exc))
        finally:
            if cdp is not None:
                cdp.close()

    for error in errors:
        print("PASI existing-browser attach: " + error, file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
