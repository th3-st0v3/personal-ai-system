"""Bounded, read-only ingestion of public GitHub text files."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TypedDict

import ingestion_service

MAX_GITHUB_BYTES = 2_000_000
ALLOWED_HOST = "api.github.com"


class GitHubFile(TypedDict):
    title: str
    content: str
    source_type: str
    version: str | None
    url: str
    path: str
    repository: str


def _parse(url: str) -> tuple[str, str, str, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST or parsed.port not in {None, 443}:
        raise ValueError("Only https://api.github.com URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("GitHub URLs must not contain credentials.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 5 or parts[0] != "repos" or parts[3] != "contents":
        raise ValueError("Expected a GitHub repository contents URL.")
    owner, repo = parts[1], parts[2]
    path = "/".join(parts[4:])
    if not owner or not repo or not path:
        raise ValueError("GitHub owner, repository, and file path are required.")
    query = urllib.parse.parse_qs(parsed.query)
    ref = query.get("ref", [""])[0]
    return owner, repo, path, ref


def fetch_public_file(url: str) -> GitHubFile:
    owner, repo, path, ref = _parse(url)
    endpoint = (
        f"https://api.github.com/repos/{urllib.parse.quote(owner)}/"
        f"{urllib.parse.quote(repo)}/contents/"
        f"{urllib.parse.quote(path, safe='/')}"
    )
    if ref:
        endpoint += "?ref=" + urllib.parse.quote(ref, safe="")
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "personal-ai-system",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(MAX_GITHUB_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub request failed with HTTP {exc.code}.") from exc
    if len(body) > MAX_GITHUB_BYTES:
        raise ValueError("GitHub file exceeds the ingestion size limit.")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict) or data.get("type") != "file" or "content" not in data:
        raise ValueError("GitHub URL did not resolve to a single file.")
    encoded_content = data.get("content")
    if not isinstance(encoded_content, str):
        raise ValueError("GitHub file did not contain encoded content.")
    try:
        normalized_base64 = "".join(encoded_content.split())
        content = base64.b64decode(normalized_base64, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("GitHub file is not valid UTF-8 base64 text.") from exc
    version_value = data.get("sha")
    if version_value is not None and not isinstance(version_value, str):
        raise ValueError("GitHub file version is invalid.")
    return {
        "title": path.rsplit("/", 1)[-1],
        "content": content,
        "source_type": "github",
        "version": version_value,
        "url": url,
        "path": path,
        "repository": f"{owner}/{repo}",
    }


def ingest_public_file(connection, project_id: int, url: str) -> dict[str, object]:
    fetched = fetch_public_file(url)
    return ingestion_service.ingest_text(
        connection,
        project_id,
        fetched["title"],
        fetched["content"],
        source_type="github",
        version=fetched["version"],
        url=fetched["url"],
    )
