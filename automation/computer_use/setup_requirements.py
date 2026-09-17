from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

SETUP_BEGIN = "PASI_SETUP_REQUIREMENTS_BEGIN"
SETUP_END = "PASI_SETUP_REQUIREMENTS_END"
MAX_SECTION_BYTES = 24_000
MAX_ITEMS = 50
MAX_TEXT = 500
RUNTIME_RELATIVE_PATH = Path(".runtime") / "automation" / "setup-requirements.json"
MARKDOWN_RELATIVE_PATH = Path(".runtime") / "automation" / "setup-requirements.md"


def _clean_text(value: Any, *, max_length: int = MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]


def _required(value: Any) -> bool:
    return value is True


def _https_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("URL is required")
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("websites and public download sources must use HTTPS")
    return normalized[:1000]


def _validate_download(item: Mapping[str, Any]) -> dict[str, Any]:
    name = _clean_text(item.get("name"))
    if not name:
        raise ValueError("download name is required")
    version = _clean_text(item.get("version"), max_length=120)
    source = item.get("source")
    normalized_source = _https_url(source) if source else ""
    return {
        "name": name,
        "version": version,
        "source": normalized_source,
        "reason": _clean_text(item.get("reason")) or "Required by the current automation task.",
        "required": _required(item.get("required")),
        "kind": _clean_text(item.get("kind"), max_length=80) or "tool",
    }


def _validate_login(item: Mapping[str, Any]) -> dict[str, Any]:
    name = _clean_text(item.get("name"))
    if not name:
        raise ValueError("login site name is required")
    url = _https_url(item.get("url"))
    verification = _clean_text(item.get("verification"), max_length=120) or "login"
    return {
        "name": name,
        "url": url,
        "reason": _clean_text(item.get("reason")) or "Interactive authentication is required before unattended use.",
        "required": _required(item.get("required")),
        "verification": verification,
    }


def parse_requirements(response: str) -> dict[str, list[dict[str, Any]]]:
    if SETUP_BEGIN not in response or SETUP_END not in response:
        return {"downloads": [], "logins": []}
    section = response.split(SETUP_BEGIN, 1)[1].split(SETUP_END, 1)[0].strip()
    if len(section.encode("utf-8")) > MAX_SECTION_BYTES:
        raise ValueError("setup requirements section exceeds configured size bound")
    payload = json.loads(section)
    if not isinstance(payload, Mapping):
        raise ValueError("setup requirements must be a JSON object")
    downloads = payload.get("downloads", [])
    logins = payload.get("logins", [])
    if not isinstance(downloads, list) or not isinstance(logins, list):
        raise ValueError("setup requirements downloads and logins must be arrays")
    if len(downloads) > MAX_ITEMS or len(logins) > MAX_ITEMS:
        raise ValueError("too many setup requirement items")
    normalized_downloads = [_validate_download(item) for item in downloads if isinstance(item, Mapping)]
    normalized_logins = [_validate_login(item) for item in logins if isinstance(item, Mapping)]
    return {"downloads": normalized_downloads, "logins": normalized_logins}


def _merge_unique(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {tuple(str(item.get(key, "")).casefold() for key in keys) for item in merged}
    for item in incoming:
        key = tuple(str(item.get(field, "")).casefold() for field in keys)
        if key in seen:
            for index, current in enumerate(merged):
                current_key = tuple(str(current.get(field, "")).casefold() for field in keys)
                if current_key == key:
                    merged[index] = {**current, **item}
                    break
        else:
            merged.append(item)
            seen.add(key)
    return merged[:MAX_ITEMS]


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"schema_version": 1, "downloads": [], "logins": []}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return {"schema_version": 1, "downloads": [], "logins": []}
    downloads = raw.get("downloads", [])
    logins = raw.get("logins", [])
    return {
        "schema_version": 1,
        "downloads": [item for item in downloads if isinstance(item, dict)][-MAX_ITEMS:],
        "logins": [item for item in logins if isinstance(item, dict)][-MAX_ITEMS:],
    }


def _render_markdown(data: Mapping[str, Any]) -> str:
    lines = [
        "# PASI Dynamic Setup Requirements",
        "",
        "This file is generated from verified task output. It contains setup metadata only; it never stores passwords, cookies, session tokens, or secret material.",
        "",
        f"Updated: {data['updated_at']}",
        "",
        "## Required downloads",
        "",
    ]
    downloads = data.get("downloads", [])
    required = [item for item in downloads if item.get("required") is True]
    optional = [item for item in downloads if item.get("required") is not True]
    if not required:
        lines.append("- None recorded yet.")
    for item in required:
        source = f" — source: {item['source']}" if item.get("source") else ""
        version = f" ({item['version']})" if item.get("version") else ""
        lines.append(f"- **{item['name']}**{version}: {item['reason']}{source}")
    lines.extend(["", "## Optional downloads", ""])
    if not optional:
        lines.append("- None recorded yet.")
    for item in optional:
        source = f" — source: {item['source']}" if item.get("source") else ""
        version = f" ({item['version']})" if item.get("version") else ""
        lines.append(f"- **{item['name']}**{version}: {item['reason']}{source}")
    lines.extend(["", "## Websites requiring interactive login", "", "PASI does not bypass CAPTCHA, Cloudflare, MFA, or other security challenges. Complete these checks manually once, then keep the browser session available for unattended work.", ""])
    logins = data.get("logins", [])
    if not logins:
        lines.append("- None recorded yet.")
    for item in logins:
        required_text = "required" if item.get("required") is True else "conditional"
        lines.append(f"- **{item['name']}** ({required_text}; {item['verification']}): {item['reason']} — {item['url']}")
    lines.append("")
    return "\n".join(lines)


def record_requirements(root: Path, requirements: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    root = root.expanduser().resolve()
    json_path = root / RUNTIME_RELATIVE_PATH
    md_path = root / MARKDOWN_RELATIVE_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_manifest(json_path)
    downloads = _merge_unique(current["downloads"], list(requirements.get("downloads", [])), ("name", "version", "source"))
    logins = _merge_unique(current["logins"], list(requirements.get("logins", [])), ("name", "url"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "downloads": downloads,
        "logins": logins,
    }
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(json_path)
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return {
        "download_count": len(downloads),
        "required_download_count": sum(item.get("required") is True for item in downloads),
        "login_count": len(logins),
        "required_login_count": sum(item.get("required") is True for item in logins),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def capture_response_requirements(root: Path, response: str) -> dict[str, Any]:
    requirements = parse_requirements(response)
    return record_requirements(root, requirements)
