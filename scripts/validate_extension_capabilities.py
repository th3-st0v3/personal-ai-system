from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "automation" / "chromium" / "pasi-chatgpt"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"

# Each non-runtime Chrome API used by the native extension must be explicitly
# declared here. "tabs" is intentionally scoped by the ChatGPT host patterns
# rather than granting the broad tabs permission.
API_CONTRACT: dict[str, dict[str, object]] = {
    "alarms": {"permission": "alarms"},
    "storage": {"permission": "storage"},
    "tabs": {
        "permission": None,
        "host_patterns": [
            "https://chatgpt.com/*",
            "https://www.chatgpt.com/*",
        ],
    },
}
PERMISSIONLESS_APIS = frozenset({"runtime"})
LOCAL_BRIDGE_HOST_PATTERN = "http://127.0.0.1:8765/*"
CHROME_API_RE = re.compile(r"\bchrome\.([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\b")
URL_RE = re.compile(r"""https?://[^\s'"<>)}\]]+""")
PYTHON_STRING_URL_RE = re.compile(r"""['"](https?://[^'"\s]+)['"]""")


def _extension_javascript_files(root: Path = EXTENSION_ROOT) -> list[Path]:
    return sorted(
        path for path in root.glob("*.js")
        if path.is_file() and not path.name.startswith("test_")
    )


def _python_browser_surface_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    roots = (
        repo_root / "scripts",
        repo_root / "automation" / "computer_use",
        repo_root / "automation" / "orchestrator",
    )
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(
                path
                for path in root.rglob("*.py")
                if path.is_file() and "/test" not in path.as_posix()
            )
    return sorted(files)


def _host_pattern_matches(url: str, pattern: str) -> bool:
    parsed = urlparse(url)
    normalized_pattern = pattern[:-1] if pattern.endswith("*") else pattern
    expected = urlparse(normalized_pattern)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        return False
    return url.startswith(normalized_pattern)


def _literal_urls(text: str) -> set[str]:
    return {value.rstrip(".,;:") for value in URL_RE.findall(text)}


def _validate_manifest_shape(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if manifest.get("manifest_version") != 3:
        errors.append("manifest_version must be 3")
    background = manifest.get("background")
    if not isinstance(background, dict) or background.get("service_worker") != "background.js":
        errors.append("background.service_worker must be background.js")
    permissions = manifest.get("permissions")
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        errors.append("permissions must be a string list")
    hosts = manifest.get("host_permissions")
    if not isinstance(hosts, list) or not all(isinstance(item, str) for item in hosts):
        errors.append("host_permissions must be a string list")
    return errors


def validate_extension_capabilities(
    *,
    manifest_path: Path = MANIFEST_PATH,
    extension_root: Path = EXTENSION_ROOT,
    python_files: Iterable[Path] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest root must be a JSON object"]

    errors.extend(_validate_manifest_shape(manifest))
    permissions = set(manifest.get("permissions", [])) if isinstance(manifest.get("permissions"), list) else set()
    host_permissions = (
        [item for item in manifest.get("host_permissions", []) if isinstance(item, str)]
        if isinstance(manifest.get("host_permissions"), list)
        else []
    )

    declared_files: list[str] = []
    content_scripts = manifest.get("content_scripts", [])
    if isinstance(content_scripts, list):
        for entry in content_scripts:
            if isinstance(entry, dict):
                declared_files.extend(item for item in entry.get("js", []) if isinstance(item, str))
    background = manifest.get("background", {})
    if isinstance(background, dict) and isinstance(background.get("service_worker"), str):
        declared_files.append(background["service_worker"])

    missing_declared = [name for name in declared_files if not (extension_root / name).is_file()]
    if missing_declared:
        errors.append(
            "manifest references missing extension files: "
            + ", ".join(sorted(set(missing_declared)))
        )

    used_apis: set[str] = set()
    extension_urls: set[str] = set()
    for path in _extension_javascript_files(extension_root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read extension source {path}: {exc}")
            continue
        used_apis.update(match.group(1) for match in CHROME_API_RE.finditer(source))
        extension_urls.update(_literal_urls(source))

    for api in sorted(used_apis):
        if api in PERMISSIONLESS_APIS:
            continue
        contract = API_CONTRACT.get(api)
        if contract is None:
            errors.append(f"chrome.{api} is used but has no declared capability contract")
            continue
        permission = contract.get("permission")
        if isinstance(permission, str) and permission not in permissions:
            errors.append(f"chrome.{api} requires manifest permission {permission!r}")
        patterns = contract.get("host_patterns", [])
        if isinstance(patterns, list):
            for pattern in patterns:
                if isinstance(pattern, str) and pattern not in host_permissions:
                    errors.append(
                        f"chrome.{api} host pattern {pattern!r} is absent from manifest host_permissions"
                    )

    for url in sorted(extension_urls):
        if not any(_host_pattern_matches(url, pattern) for pattern in host_permissions):
            errors.append(
                f"extension source URL is not covered by manifest host_permissions: {url}"
            )

    py_files = list(python_files) if python_files is not None else _python_browser_surface_files()
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
        except (OSError, SyntaxError):
            continue
        for match in PYTHON_STRING_URL_RE.finditer(source):
            url = match.group(1)
            parsed = urlparse(url)
            if parsed.hostname == "127.0.0.1" and parsed.port == 8765:
                if not _host_pattern_matches(url, LOCAL_BRIDGE_HOST_PATTERN):
                    errors.append(
                        f"Python bridge URL is outside the native extension bridge contract: {url}"
                    )

    if LOCAL_BRIDGE_HOST_PATTERN not in host_permissions:
        errors.append(
            f"required PASI bridge host permission is missing: {LOCAL_BRIDGE_HOST_PATTERN}"
        )

    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PASI native extension capability boundaries."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    errors = validate_extension_capabilities(
        manifest_path=args.manifest,
        extension_root=args.manifest.parent,
    )
    if errors:
        print("PASI extension capability validation: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASI extension capability validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
