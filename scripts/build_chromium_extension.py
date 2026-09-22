#!/usr/bin/env python3
"""Create a cache-free unpacked Chromium extension staging directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


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


def build_extension(output: Path = DEFAULT_OUTPUT) -> Path:
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
