#!/usr/bin/env python3
"""Create a cache-free unpacked Chromium extension staging directory."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "automation" / "chromium" / "pasi-chatgpt"
DEFAULT_OUTPUT = ROOT / ".runtime" / "chromium" / "pasi-chatgpt"

EXTENSION_FILES = (
    "manifest.json",
    "timeout-config.js",
    "timeout-policy.json",
    "background.js",
    "detectors.js",
    "content.js",
    "recovery_progress.js",
    "recovery.js",
    "sidepanel.html",
    "sidepanel.css",
    "sidepanel.js",
)


def validate_test_bridge_url(bridge_url: str) -> str:
    parsed = urlparse(bridge_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path:
        raise ValueError("test bridge URL must be an http://127.0.0.1[:port] URL")
    return bridge_url.rstrip("/")


def build_extension(output: Path = DEFAULT_OUTPUT, *, bridge_url: str | None = None) -> Path:
    output = output.resolve()
    source = SOURCE.resolve()
    if output == source or source in output.parents:
        raise ValueError("refusing to place generated extension inside the source tree")

    preserved_bridge_token = None
    bridge_token_path = output / ".bridge-token"
    if bridge_token_path.is_file():
        preserved_bridge_token = bridge_token_path.read_bytes()

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in EXTENSION_FILES:
        source_file = source / relative
        if not source_file.is_file():
            raise FileNotFoundError(source_file)
        shutil.copy2(source_file, output / relative)

    if bridge_url is not None:
        bridge = validate_test_bridge_url(bridge_url)
        background = output / "background.js"
        background_text = background.read_text(encoding="utf-8")
        background_text = background_text.replace(
            "const BRIDGE = 'http://127.0.0.1:8765';",
            "const BRIDGE = '" + bridge + "';",
        )
        background.write_text(background_text, encoding="utf-8")
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["host_permissions"] = [
            bridge + "/*" if item == "http://127.0.0.1:8765/*" else item
            for item in manifest.get("host_permissions", [])
        ]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # The bridge token is a host-local runtime secret, not a source-controlled
    # extension asset. Preserve it across rebuilds so refreshing the generated
    # bundle does not silently disconnect an already loaded native controller.
    if preserved_bridge_token is not None:
        bridge_token_path.write_bytes(preserved_bridge_token)
        bridge_token_path.chmod(0o600)

    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a cache-free PASI Chromium extension directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = build_extension(args.output)
    print(f"PASI Chromium extension staging directory: {output}")
    print(f"Files copied: {', '.join(EXTENSION_FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
