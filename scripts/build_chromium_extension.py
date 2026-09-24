#!/usr/bin/env python3
"""Create a cache-free unpacked Chromium extension staging directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from zipfile import ZipFile


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

FORBIDDEN_SUFFIXES = frozenset({".pyc", ".pyo"})
FORBIDDEN_COMPONENT_PREFIX = "_"


def validate_extension_tree(root: Path) -> None:
    """Reject any path Chrome could interpret as an invalid unpacked-extension entry."""
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(component.startswith(FORBIDDEN_COMPONENT_PREFIX) for component in relative.parts):
            raise RuntimeError(f"invalid Chromium extension staging entry: {relative}")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"Python bytecode is forbidden in Chromium extension staging: {relative}")


def validate_manifest_files(root: Path) -> None:
    """Ensure every local file named by the MV3 manifest is present in staging."""
    import json

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    required = set()
    background = manifest.get("background", {})
    if isinstance(background, dict) and isinstance(background.get("service_worker"), str):
        required.add(background["service_worker"])
    action = manifest.get("action", {})
    if isinstance(action, dict) and isinstance(action.get("default_popup"), str):
        required.add(action["default_popup"])
    side_panel = manifest.get("side_panel", {})
    if isinstance(side_panel, dict) and isinstance(side_panel.get("default_path"), str):
        required.add(side_panel["default_path"])
    for script_group in manifest.get("content_scripts", []):
        if isinstance(script_group, dict):
            required.update(item for item in script_group.get("js", []) if isinstance(item, str))
            required.update(item for item in script_group.get("css", []) if isinstance(item, str))
    for resource_group in manifest.get("web_accessible_resources", []):
        if isinstance(resource_group, dict):
            required.update(item for item in resource_group.get("resources", []) if isinstance(item, str))
    icons = manifest.get("icons", {})
    if isinstance(icons, dict):
        required.update(item for item in icons.values() if isinstance(item, str))
    missing = sorted(path for path in required if not (root / path).is_file())
    if missing:
        raise RuntimeError("manifest-declared extension files missing from staging: " + ", ".join(missing))


def build_extension(output: Path = DEFAULT_OUTPUT) -> Path:
    output = output.resolve()
    source = SOURCE.resolve()
    if output == source or source in output.parents:
        raise ValueError("refusing to place generated extension inside the source tree")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in EXTENSION_FILES:
        source_file = source / relative
        if not source_file.is_file():
            raise FileNotFoundError(source_file)
        shutil.copy2(source_file, output / relative)

    # The native background worker authenticates bridge requests with the
    # per-user token provisioned at ~/.pasi/bridge-token. Rebuilding the
    # unpacked staging directory must preserve that runtime credential.
    home_token = Path.home() / ".pasi" / "bridge-token"
    staging_token = output / ".bridge-token"
    if home_token.is_file() and home_token.stat().st_size > 0:
        shutil.copy2(home_token, staging_token)
        staging_token.chmod(0o600)

    validate_extension_tree(output)
    validate_manifest_files(output)
    return output


def build_extension_archive(output: Path = DEFAULT_OUTPUT) -> Path:
    """Build a zip containing only the sanitized unpacked-extension directory."""
    output = build_extension(output)
    archive_base = output.with_suffix("")
    archive = Path(shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=output.parent,
        base_dir=output.name,
    ))
    with ZipFile(archive) as handle:
        for member in handle.infolist():
            relative = Path(member.filename)
            if any(component.startswith(FORBIDDEN_COMPONENT_PREFIX) for component in relative.parts):
                raise RuntimeError(f"invalid Chromium extension archive entry: {member.filename}")
            if not member.is_dir() and relative.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise RuntimeError(f"Python bytecode is forbidden in Chromium extension archive: {member.filename}")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a cache-free PASI Chromium extension directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--archive",
        action="store_true",
        help="also create a cache-free .zip next to the unpacked staging directory",
    )
    args = parser.parse_args()

    output = build_extension(args.output)
    print(f"PASI Chromium extension staging directory: {output}")
    print(f"Files copied: {', '.join(EXTENSION_FILES)}")
    if args.archive:
        archive = build_extension_archive(args.output)
        print(f"PASI Chromium extension archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
